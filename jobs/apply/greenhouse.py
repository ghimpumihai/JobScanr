"""Greenhouse Boards API v1 job application submitter and question schema parser.

API Docs & Endpoints:
- GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{id}?questions=true
- POST https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{id} (multipart/form-data)
"""

from __future__ import annotations

import io
import logging
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from jobs.apply.base import (
    BaseSubmitter,
    QuestionOption,
    QuestionType,
    ScreeningQuestion,
    SubmissionResult,
    SubmitResponse,
    get_candidate_names,
    get_candidate_phone,
    map_screening_question,
)
from models import JobPosting, User

logger = logging.getLogger(__name__)


def extract_greenhouse_identifiers(posting: JobPosting) -> tuple[str, str]:
    """Extract (board_token, job_id) from job posting record or URL."""
    job_id = str(posting.get("external_id") or "").strip()
    board_token = str(posting.get("ats_identifier") or "").strip()

    if board_token and job_id:
        return board_token, job_id

    url = posting.get("url") or ""
    if url:
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.strip("/").split("/") if p]
        # Example: https://boards.greenhouse.io/stripe/jobs/123456 or /embed/job_app?for=stripe&token=123456
        if "greenhouse.io" in parsed.netloc:
            query_params = parse_qs(parsed.query)
            if "for" in query_params and not board_token:
                board_token = query_params["for"][0]
            if "token" in query_params and not job_id:
                job_id = query_params["token"][0]

            if not (board_token and job_id):
                if len(path_parts) >= 3 and path_parts[1] == "jobs":
                    if not board_token:
                        board_token = path_parts[0]
                    if not job_id:
                        job_id = path_parts[2]
                elif len(path_parts) >= 1 and not board_token and path_parts[0] != "embed":
                    board_token = path_parts[0]

    return board_token, job_id


class GreenhouseSubmitter(BaseSubmitter):
    """Submitter for Greenhouse public job boards."""

    async def fetch_questions(self, posting: JobPosting) -> list[ScreeningQuestion]:
        """Fetch and parse live screening questions for Greenhouse job opening."""
        board_token, job_id = extract_greenhouse_identifiers(posting)
        if not board_token or not job_id:
            raise ValueError(f"Missing Greenhouse board_token or job_id in posting: {posting.get('title')}")

        url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}"
        params = {"questions": "true"}

        async def _fetch(cli: httpx.AsyncClient) -> httpx.Response:
            return await cli.get(url, params=params, timeout=15.0)

        if self.client:
            resp = await _fetch(self.client)
        else:
            async with httpx.AsyncClient() as cli:
                resp = await _fetch(cli)

        resp.raise_for_status()
        data = resp.json()
        raw_questions = data.get("questions") or []

        parsed_questions: list[ScreeningQuestion] = []
        for q in raw_questions:
            q_id = q.get("id") or 0
            label = (q.get("label") or "").strip()
            required = bool(q.get("required", False))
            fields = q.get("fields") or []

            raw_field_name: str | None = None
            q_type = QuestionType.SHORT_TEXT
            options: list[QuestionOption] = []

            if fields:
                primary_field = fields[0]
                raw_field_name = primary_field.get("name")
                field_type = primary_field.get("type", "input_text")

                if field_type == "textarea":
                    q_type = QuestionType.LONG_TEXT
                elif field_type == "multi_value_single_select":
                    q_type = QuestionType.SINGLE_SELECT
                    for v in primary_field.get("values") or []:
                        opt_id = v.get("value") if "value" in v else v.get("id")
                        opt_label = v.get("label") or str(opt_id)
                        options.append(QuestionOption(id=opt_id, label=opt_label))
                elif field_type == "multi_value_multi_select":
                    q_type = QuestionType.MULTI_SELECT
                    for v in primary_field.get("values") or []:
                        opt_id = v.get("value") if "value" in v else v.get("id")
                        opt_label = v.get("label") or str(opt_id)
                        options.append(QuestionOption(id=opt_id, label=opt_label))
                elif field_type == "input_file":
                    q_type = QuestionType.FILE
                elif field_type == "boolean":
                    q_type = QuestionType.BOOLEAN
                else:
                    q_type = QuestionType.SHORT_TEXT

            if not raw_field_name:
                raw_field_name = f"question_{q_id}"

            parsed_questions.append(
                ScreeningQuestion(
                    id=q_id,
                    label=label,
                    question_type=q_type,
                    required=required,
                    options=options,
                    raw_field_name=raw_field_name,
                    description=q.get("description"),
                )
            )

        return parsed_questions

    def map_and_validate_payload(
        self,
        user: User,
        posting: JobPosting,
        questions: list[ScreeningQuestion],
    ) -> SubmissionResult:
        """Map user profile into Greenhouse form fields and evaluate question confidence."""
        board_token, _ = extract_greenhouse_identifiers(posting)
        _, first_name, last_name = get_candidate_names(user)
        email = user.get("email") or ""
        phone = get_candidate_phone(user)

        payload: dict[str, Any] = {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "phone": phone,
        }
        if board_token:
            payload["mapped_url_token"] = board_token

        unmapped: list[ScreeningQuestion] = []
        has_captcha = False

        for q in questions:
            field_name = q.raw_field_name or f"question_{q.id}"
            clean_label = q.label.lower()

            # Skip standard fields already in base payload
            if clean_label in ("first name", "last name", "email", "phone", "resume", "cover letter"):
                continue

            # Detect reCAPTCHA token fields
            if "recaptcha" in field_name.lower() or "recaptcha" in clean_label:
                has_captcha = True
                continue

            mapped_value, is_confident = map_screening_question(q, user)
            if is_confident and mapped_value is not None:
                payload[field_name] = mapped_value
            else:
                if q.required:
                    unmapped.append(q)

        if has_captcha:
            return SubmissionResult(
                status="manual_apply",
                payload=payload,
                unmapped_questions=unmapped,
                reason="captcha_blocked",
            )

        if unmapped:
            return SubmissionResult(
                status="needs_review",
                payload=payload,
                unmapped_questions=unmapped,
                reason=f"{len(unmapped)} required question(s) unmapped or require manual answer",
            )

        return SubmissionResult(
            status="ready",
            payload=payload,
            unmapped_questions=[],
            reason=None,
        )

    async def submit(
        self,
        user: User,
        posting: JobPosting,
        payload: dict[str, Any],
        resume_stream: io.BytesIO,
        filename: str,
        content_type: str = "application/pdf",
    ) -> SubmitResponse:
        """Submit multipart form application to Greenhouse Boards API."""
        board_token, job_id = extract_greenhouse_identifiers(posting)
        if not board_token or not job_id:
            return SubmitResponse(
                status="failed",
                reason="missing_identifiers",
                error_message="Could not resolve Greenhouse board_token or job_id",
            )

        url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}"
        resume_bytes = resume_stream.getvalue()
        files = {
            "resume": (filename, resume_bytes, content_type),
        }

        # Convert boolean / integer values to string format for form-data, preserving lists
        data: dict[str, Any] = {}
        for k, v in payload.items():
            if isinstance(v, bool):
                data[k] = "true" if v else "false"
            elif isinstance(v, (list, tuple)):
                data[k] = [str(item) for item in v]
            else:
                data[k] = str(v)

        async def _send(cli: httpx.AsyncClient) -> httpx.Response:
            return await cli.post(url, data=data, files=files, timeout=20.0)

        try:
            if self.client:
                resp = await _send(self.client)
            else:
                async with httpx.AsyncClient() as cli:
                    resp = await _send(cli)
        except httpx.RequestError as exc:
            logger.warning("Network error submitting to Greenhouse: %s", exc)
            return SubmitResponse(
                status="failed",
                reason="network_error",
                error_message=str(exc),
            )

        if resp.status_code in (200, 201):
            try:
                res_data = resp.json()
            except Exception:
                res_data = {}
            app_id = res_data.get("id") or res_data.get("application_id")
            redirect = res_data.get("redirect") or res_data.get("redirect_url")
            return SubmitResponse(
                status="submitted",
                external_application_id=str(app_id) if app_id else None,
                redirect_url=str(redirect) if redirect else None,
                http_status=resp.status_code,
            )

        if resp.status_code == 404:
            return SubmitResponse(
                status="stale_closed",
                reason="job_closed",
                http_status=404,
                error_message="Job opening no longer exists on Greenhouse board",
            )

        resp_text = resp.text.lower()
        if resp.status_code in (400, 422):
            if any(term in resp_text for term in ("captcha", "recaptcha", "robot", "turnstile")):
                return SubmitResponse(
                    status="manual_apply",
                    reason="captcha_blocked",
                    http_status=resp.status_code,
                    error_message=resp.text,
                )
            return SubmitResponse(
                status="needs_review",
                reason="validation_error",
                http_status=resp.status_code,
                error_message=resp.text,
            )

        if resp.status_code == 429:
            return SubmitResponse(
                status="failed",
                reason="rate_limited",
                http_status=429,
                error_message=resp.text,
            )

        return SubmitResponse(
            status="failed",
            reason="server_error",
            http_status=resp.status_code,
            error_message=resp.text,
        )
