"""Resilient application queue worker with domain throttling and crash recovery.

Drains queued applications using PostgreSQL SKIP LOCKED without connection pool
starvation or domain flooding.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import httpx

from db.queries import (
    claim_next_queued_application,
    reap_stalled_applications,
    transition_application_status,
)
from jobs.apply.base import BaseSubmitter, ManualApplySubmitter
from jobs.apply.cv_storage import download_resume_stream
from jobs.apply.greenhouse import GreenhouseSubmitter
from jobs.apply.lever import LeverSubmitter

logger = logging.getLogger(__name__)


def resolve_submitter(platform: str, client: httpx.AsyncClient | None = None) -> BaseSubmitter:
    """Resolve the appropriate submitter for a given ATS platform."""
    plat = (platform or "").lower().strip()
    if plat == "greenhouse":
        return GreenhouseSubmitter(client=client)
    if plat == "lever":
        return LeverSubmitter(client=client)
    return ManualApplySubmitter(client=client)


@dataclass
class ApplicationClaim:
    """In-memory representation of an application claimed from the queue."""

    id: int
    user_id: int
    job_posting_id: int
    company_id: int
    company_name: str
    ats_platform: str
    ats_identifier: str
    job_url: str
    job_title: str
    attempt_token: str
    attempts: int
    screening_defaults: dict[str, Any]
    resume_data: dict[str, Any]
    resume_storage_path: str | None
    resume_filename: str | None
    resume_content_type: str | None


@dataclass
class ProcessingResult:
    """Outcome of processing an application claim."""

    application_id: int
    final_status: Literal["submitted", "needs_review", "manual_apply", "stale_closed", "failed", "queued"]
    reason: str | None = None
    confirmation_id: str | None = None
    submitted_payload: dict[str, Any] | None = None


def _handle_failure(app_id: int, attempts: int, reason: str) -> ProcessingResult:
    """Schedule a 15-minute retry if attempts < 3, else transition to failed."""
    if attempts < 3:
        retry_at = datetime.now(timezone.utc) + timedelta(minutes=15)
        transition_application_status(
            application_id=app_id,
            to_status="queued",
            from_status="submitting",
            reason=reason,
            next_attempt_at=retry_at,
        )
        return ProcessingResult(application_id=app_id, final_status="queued", reason=reason)

    transition_application_status(
        application_id=app_id,
        to_status="failed",
        from_status="submitting",
        reason=f"max_attempts_exceeded: {reason}",
    )
    return ProcessingResult(application_id=app_id, final_status="failed", reason=f"max_attempts_exceeded: {reason}")


async def check_posting_liveness(url: str, client: httpx.AsyncClient | None = None) -> bool | None:
    """Check if the target job posting URL is live and accepting applications.

    Returns:
        True: Accessible and open (< 400).
        False: Definitively closed (HTTP 404, 410).
        None: Indeterminate due to network error, connection timeout, or 5xx.
    """
    if not url or not url.strip():
        return False

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    should_close_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=15.0, follow_redirects=True, headers=headers)
        should_close_client = True

    try:
        try:
            resp = await client.head(url, follow_redirects=True)
            if resp.status_code in (404, 410):
                return False
            if resp.status_code < 400:
                return True
        except (httpx.HTTPError, httpx.RequestError):
            pass

        resp = await client.get(url, follow_redirects=True)
        if resp.status_code in (404, 410):
            return False
        if resp.status_code < 400:
            return True
        return None
    except (httpx.HTTPError, httpx.RequestError) as err:
        logger.warning("Liveness check network error for %s: %s", url, err)
        return None
    finally:
        if should_close_client:
            await client.aclose()


async def process_application(
    claim: ApplicationClaim | dict[str, Any],
    dry_run: bool = False,
    client: httpx.AsyncClient | None = None,
) -> ProcessingResult:
    """Process an application claim end-to-end.

    Flow:
    1. Pre-submission liveness check on job_url -> stale_closed if 404/410, retry on network error.
    2. Check candidate CV storage path -> needs_review if missing.
    3. Stream candidate CV in-memory.
    4. Fetch questions & validate required mappings.
    5. Fallback to manual_apply (captcha/unsupported) or needs_review (unmapped/essay).
    6. Dispatch multipart submission to ATS endpoint.
    7. Update application state and record audit event.
    """
    if isinstance(claim, dict):
        claim = ApplicationClaim(**claim)

    resume_filename = claim.resume_filename or "resume.pdf"
    resume_content_type = claim.resume_content_type or "application/pdf"

    # 1. Liveness Gate
    liveness = await check_posting_liveness(claim.job_url, client=client)
    if liveness is False:
        transition_application_status(
            application_id=claim.id,
            to_status="stale_closed",
            from_status="submitting",
            reason="posting_url_not_found_404",
        )
        return ProcessingResult(
            application_id=claim.id,
            final_status="stale_closed",
            reason="posting_url_not_found_404",
        )
    if liveness is None:
        return _handle_failure(claim.id, claim.attempts, "liveness_check_network_error")

    # 2. Candidate CV Validation
    if not claim.resume_storage_path:
        transition_application_status(
            application_id=claim.id,
            to_status="needs_review",
            from_status="submitting",
            reason="resume_file_missing",
        )
        return ProcessingResult(
            application_id=claim.id,
            final_status="needs_review",
            reason="resume_file_missing",
        )

    # 3. In-Memory CV Retrieval
    try:
        resume_stream = download_resume_stream(claim.resume_storage_path)
    except Exception as err:
        logger.error("Failed to retrieve CV stream for app %s: %s", claim.id, err)
        transition_application_status(
            application_id=claim.id,
            to_status="needs_review",
            from_status="submitting",
            reason=f"cv_download_failed: {err}",
        )
        return ProcessingResult(
            application_id=claim.id,
            final_status="needs_review",
            reason=f"cv_download_failed: {err}",
        )

    # 4. Resolve Submitter
    submitter = resolve_submitter(claim.ats_platform, client=client)

    user_dict: dict[str, Any] = {
        "id": claim.user_id,
        "screening_defaults": claim.screening_defaults,
        "resume_data": claim.resume_data,
        "resume_storage_path": claim.resume_storage_path,
        "resume_filename": resume_filename,
        "resume_content_type": resume_content_type,
    }
    posting_dict: dict[str, Any] = {
        "id": claim.job_posting_id,
        "company_id": claim.company_id,
        "company_name": claim.company_name,
        "ats_platform": claim.ats_platform,
        "ats_identifier": claim.ats_identifier,
        "url": claim.job_url,
        "title": claim.job_title,
    }

    if isinstance(submitter, ManualApplySubmitter):
        transition_application_status(
            application_id=claim.id,
            to_status="manual_apply",
            from_status="submitting",
            reason=f"platform_{claim.ats_platform}_requires_manual_apply",
        )
        return ProcessingResult(
            application_id=claim.id,
            final_status="manual_apply",
            reason=f"platform_{claim.ats_platform}_requires_manual_apply",
        )

    # 5. Fetch Questions & Map Schema
    try:
        questions = await submitter.fetch_questions(posting_dict)  # type: ignore[arg-type]
        mapping_result = submitter.map_and_validate_payload(user_dict, posting_dict, questions)  # type: ignore[arg-type]
    except Exception as err:
        logger.error("Question fetch/mapping failed for app %s: %s", claim.id, err)
        transition_application_status(
            application_id=claim.id,
            to_status="needs_review",
            from_status="submitting",
            reason=f"mapping_error: {err}",
        )
        return ProcessingResult(
            application_id=claim.id,
            final_status="needs_review",
            reason=f"mapping_error: {err}",
        )

    if mapping_result.status == "manual_apply":
        transition_application_status(
            application_id=claim.id,
            to_status="manual_apply",
            from_status="submitting",
            reason=mapping_result.reason,
        )
        return ProcessingResult(
            application_id=claim.id,
            final_status="manual_apply",
            reason=mapping_result.reason,
        )

    if mapping_result.status == "needs_review":
        payload_record = {"custom_answers": getattr(mapping_result, "custom_answers", {})}
        transition_application_status(
            application_id=claim.id,
            to_status="needs_review",
            from_status="submitting",
            reason=mapping_result.reason,
            submitted_payload=payload_record,
        )
        return ProcessingResult(
            application_id=claim.id,
            final_status="needs_review",
            reason=mapping_result.reason,
            submitted_payload=payload_record,
        )

    # 6. Execute Submission
    if dry_run:
        dry_payload = {"dry_run": True, "payload": mapping_result.payload}
        transition_application_status(
            application_id=claim.id,
            to_status="submitted",
            from_status="submitting",
            reason="dry_run_simulation",
            submitted_payload=dry_payload,
        )
        return ProcessingResult(
            application_id=claim.id,
            final_status="submitted",
            reason="dry_run_simulation",
            submitted_payload=dry_payload,
        )

    try:
        submit_resp = await submitter.submit(
            user=user_dict,  # type: ignore[arg-type]
            posting=posting_dict,  # type: ignore[arg-type]
            payload=mapping_result.payload,
            resume_stream=resume_stream,
            filename=resume_filename,
            content_type=resume_content_type,
        )
    except Exception as err:
        logger.error("HTTP submission exception for app %s: %s", claim.id, err)
        return _handle_failure(claim.id, claim.attempts, f"network_exception: {err}")

    if submit_resp.status == "submitted":
        conf = {
            "submitted": True,
            "confirmation_id": submit_resp.external_application_id,
            "external_application_id": submit_resp.external_application_id,
            "redirect_url": submit_resp.redirect_url,
        }
        transition_application_status(
            application_id=claim.id,
            to_status="submitted",
            from_status="submitting",
            reason="submission_successful",
            submitted_payload=conf,
        )
        return ProcessingResult(
            application_id=claim.id,
            final_status="submitted",
            reason="submission_successful",
            confirmation_id=submit_resp.external_application_id,
            submitted_payload=conf,
        )

    if submit_resp.status == "manual_apply":
        transition_application_status(
            application_id=claim.id,
            to_status="manual_apply",
            from_status="submitting",
            reason=submit_resp.reason,
        )
        return ProcessingResult(
            application_id=claim.id,
            final_status="manual_apply",
            reason=submit_resp.reason,
        )

    if submit_resp.status == "stale_closed":
        transition_application_status(
            application_id=claim.id,
            to_status="stale_closed",
            from_status="submitting",
            reason=submit_resp.reason,
        )
        return ProcessingResult(
            application_id=claim.id,
            final_status="stale_closed",
            reason=submit_resp.reason,
        )

    return _handle_failure(claim.id, claim.attempts, submit_resp.reason or "submit_failed")


def reap_stuck_applications(timeout_minutes: int = 5) -> int:
    """Reap applications stranded in 'submitting' beyond timeout_minutes."""
    return reap_stalled_applications(stalled_threshold_seconds=timeout_minutes * 60)


async def run_queue_worker(
    poll_interval: float = 5.0,
    dry_run: bool = False,
    max_iterations: int | None = None,
    domain_throttle_seconds: int = 60,
    reaper_interval_seconds: float = 300.0,
) -> int:
    """Run the resilient application queue worker loop.

    Polls for eligible applications, submits them while enforcing domain
    spacing, and releases database connections immediately.
    """
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Termination signal received; stopping queue worker gracefully...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except (NotImplementedError, RuntimeError):
            pass

    processed_count = 0
    iteration = 0
    last_reaper_run = 0.0

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as http_client:
        while not stop_event.is_set():
            if max_iterations is not None and iteration >= max_iterations:
                break
            iteration += 1

            # Run crash recovery reaper periodically
            now = loop.time()
            if now - last_reaper_run >= reaper_interval_seconds:
                reaped = reap_stuck_applications(timeout_minutes=5)
                if reaped > 0:
                    logger.warning("Reaped %d stalled applications into needs_review", reaped)
                last_reaper_run = now

            # Claim application - DB connection is opened and committed/closed immediately inside query
            claim_dict = claim_next_queued_application(domain_throttle_seconds=domain_throttle_seconds)
            if claim_dict is None:
                # No eligible jobs ready or all companies throttled; sleep without holding any DB connection
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
                except asyncio.TimeoutError:
                    pass
                continue

            claim = ApplicationClaim(
                id=claim_dict["id"],
                user_id=claim_dict["user_id"],
                job_posting_id=claim_dict["job_posting_id"],
                company_id=claim_dict["company_id"],
                company_name=claim_dict["company_name"],
                ats_platform=claim_dict["ats_platform"],
                ats_identifier=claim_dict["ats_identifier"],
                job_url=claim_dict["job_url"],
                job_title=claim_dict["job_title"],
                attempt_token=claim_dict["attempt_token"],
                attempts=claim_dict["attempts"],
                screening_defaults=claim_dict["screening_defaults"],
                resume_data=claim_dict["resume_data"],
                resume_storage_path=claim_dict["resume_storage_path"],
                resume_filename=claim_dict["resume_filename"],
                resume_content_type=claim_dict["resume_content_type"],
            )

            result = await process_application(claim, dry_run=dry_run, client=http_client)
            processed_count += 1
            logger.info("Application %d resolved to status: %s", result.application_id, result.final_status)

    return processed_count
