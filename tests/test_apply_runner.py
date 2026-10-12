import asyncio
import io
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from db import queries
from jobs.apply.base import SubmissionResult, SubmitResponse
from jobs.apply.runner import (
    ApplicationClaim,
    ProcessingResult,
    check_posting_liveness,
    process_application,
    reap_stuck_applications,
    run_queue_worker,
)


@pytest.fixture(autouse=True)
def reset_pool():
    queries.close_pool()
    yield
    queries.close_pool()


# ---------------------------------------------------------------------------
# Database Queue Queries
# ---------------------------------------------------------------------------


def test_claim_next_queued_application_success():
    mock_conn = MagicMock()
    mock_cur = MagicMock()

    # row columns:
    # 0: id, 1: user_id, 2: job_posting_id, 3: company_id, 4: company_name,
    # 5: ats_platform, 6: ats_identifier, 7: job_url, 8: job_title,
    # 9: attempt_token, 10: attempts,
    # 11: screening_defaults, 12: resume_data, 13: resume_storage_path,
    # 14: resume_filename, 15: resume_content_type
    mock_cur.fetchone.return_value = (
        101,
        1,
        501,
        20,
        "Stripe",
        "greenhouse",
        "stripe",
        "https://boards.greenhouse.io/stripe/jobs/501",
        "Software Engineer",
        "00000000-0000-0000-0000-000000000099",
        1,
        json.dumps({"first_name": "Jane", "email": "jane@example.com"}),
        {"skills": ["python", "distributed systems"]},
        "1/resume.pdf",
        "resume.pdf",
        "application/pdf",
    )
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch("db.queries.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        claim = queries.claim_next_queued_application(domain_throttle_seconds=60)

        assert claim is not None
        assert claim["id"] == 101
        assert claim["company_name"] == "Stripe"
        assert claim["ats_platform"] == "greenhouse"
        assert claim["screening_defaults"]["first_name"] == "Jane"
        assert claim["resume_data"]["skills"] == ["python", "distributed systems"]
        assert claim["resume_storage_path"] == "1/resume.pdf"

        # Verify event was logged
        assert mock_cur.execute.call_count == 2
        event_call = mock_cur.execute.call_args_list[1]
        assert "INSERT INTO application_events" in event_call[0][0]
        assert event_call[0][1] == (101,)


def test_claim_next_queued_application_empty_queue():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = None
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch("db.queries.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        claim = queries.claim_next_queued_application(domain_throttle_seconds=60)
        assert claim is None
        assert mock_cur.execute.call_count == 1


def test_transition_application_status():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.rowcount = 1
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch("db.queries.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        res = queries.transition_application_status(
            application_id=101,
            to_status="submitted",
            from_status="submitting",
            reason="submission_successful",
            submitted_payload={"confirmation_id": "CONF-123"},
        )
        assert res is True
        assert mock_cur.execute.call_count == 2
        update_call = mock_cur.execute.call_args_list[0]
        assert "UPDATE applications" in update_call[0][0]
        event_call = mock_cur.execute.call_args_list[1]
        assert "INSERT INTO application_events" in event_call[0][0]
        assert event_call[0][1] == (101, "submitting", "submitted", "submission_successful")


def test_transition_application_status_not_found():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.rowcount = 0
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch("db.queries.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        res = queries.transition_application_status(
            application_id=999,
            to_status="submitted",
        )
        assert res is False
        assert mock_cur.execute.call_count == 1


def test_reap_stalled_applications():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.rowcount = 3
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch("db.queries.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        reaped = queries.reap_stalled_applications(stalled_threshold_seconds=300)
        assert reaped == 3
        sql_call = mock_cur.execute.call_args[0]
        assert "WITH stalled AS" in sql_call[0]
        assert "worker_timeout_unconfirmed" in sql_call[0]
        assert sql_call[1] == (300,)


# ---------------------------------------------------------------------------
# Pre-Submission Liveness Gate
# ---------------------------------------------------------------------------


def test_check_posting_liveness_active():
    async def run():
        transport = httpx.MockTransport(lambda req: httpx.Response(200, text="Job active"))
        async with httpx.AsyncClient(transport=transport) as client:
            is_live = await check_posting_liveness("https://boards.greenhouse.io/stripe/jobs/123", client=client)
            assert is_live is True

    asyncio.run(run())


def test_check_posting_liveness_404_closed():
    async def run():
        transport = httpx.MockTransport(lambda req: httpx.Response(404, text="Job not found"))
        async with httpx.AsyncClient(transport=transport) as client:
            is_live = await check_posting_liveness("https://boards.greenhouse.io/stripe/jobs/404", client=client)
            assert is_live is False

    asyncio.run(run())


def test_check_posting_liveness_fallback_to_get_on_405():
    async def run():
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "HEAD":
                return httpx.Response(405)
            return httpx.Response(200, text="Active via GET")

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            is_live = await check_posting_liveness("https://jobs.lever.co/postings/123", client=client)
            assert is_live is True

    asyncio.run(run())


def test_check_posting_liveness_network_error():
    async def run():
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Failed to connect")

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            is_live = await check_posting_liveness("https://broken.invalid/jobs/123", client=client)
            assert is_live is None

    asyncio.run(run())


def test_check_posting_liveness_empty_url():
    async def run():
        assert await check_posting_liveness("") is False
        assert await check_posting_liveness("   ") is False

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Application Processing Pipeline
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_claim() -> ApplicationClaim:
    return ApplicationClaim(
        id=101,
        user_id=1,
        job_posting_id=501,
        company_id=20,
        company_name="Stripe",
        ats_platform="greenhouse",
        ats_identifier="stripe",
        job_url="https://boards.greenhouse.io/stripe/jobs/501",
        job_title="Backend Engineer",
        attempt_token="00000000-0000-0000-0000-000000000099",
        attempts=1,
        screening_defaults={"first_name": "Jane", "last_name": "Doe", "email": "jane@example.com"},
        resume_data={"skills": ["python"]},
        resume_storage_path="1/resume.pdf",
        resume_filename="resume.pdf",
        resume_content_type="application/pdf",
    )


def test_process_application_liveness_404_transitions_to_stale_closed(sample_claim):
    async def run():
        with (
            patch("jobs.apply.runner.check_posting_liveness", new_callable=AsyncMock) as mock_liveness,
            patch("jobs.apply.runner.transition_application_status") as mock_transition,
        ):
            mock_liveness.return_value = False

            res = await process_application(sample_claim)

            assert res.final_status == "stale_closed"
            assert res.reason == "posting_url_not_found_404"
            mock_transition.assert_called_once_with(
                application_id=101,
                to_status="stale_closed",
                from_status="submitting",
                reason="posting_url_not_found_404",
            )

    asyncio.run(run())


def test_process_application_liveness_network_error_schedules_retry(sample_claim):
    async def run():
        with (
            patch("jobs.apply.runner.check_posting_liveness", new_callable=AsyncMock) as mock_liveness,
            patch("jobs.apply.runner.transition_application_status") as mock_transition,
        ):
            mock_liveness.return_value = None

            res = await process_application(sample_claim)

            assert res.final_status == "queued"
            assert res.reason == "liveness_check_network_error"
            mock_transition.assert_called_once()
            assert mock_transition.call_args[1]["to_status"] == "queued"
            assert mock_transition.call_args[1]["next_attempt_at"] is not None

    asyncio.run(run())


def test_process_application_missing_resume_path(sample_claim):
    async def run():
        sample_claim.resume_storage_path = None
        with (
            patch("jobs.apply.runner.check_posting_liveness", new_callable=AsyncMock) as mock_liveness,
            patch("jobs.apply.runner.transition_application_status") as mock_transition,
        ):
            mock_liveness.return_value = True

            res = await process_application(sample_claim)

            assert res.final_status == "needs_review"
            assert res.reason == "resume_file_missing"
            mock_transition.assert_called_once_with(
                application_id=101,
                to_status="needs_review",
                from_status="submitting",
                reason="resume_file_missing",
            )

    asyncio.run(run())


def test_process_application_cv_download_failure(sample_claim):
    async def run():
        with (
            patch("jobs.apply.runner.check_posting_liveness", new_callable=AsyncMock) as mock_liveness,
            patch("jobs.apply.runner.download_resume_stream") as mock_download,
            patch("jobs.apply.runner.transition_application_status") as mock_transition,
        ):
            mock_liveness.return_value = True
            mock_download.side_effect = RuntimeError("S3 connection reset")

            res = await process_application(sample_claim)

            assert res.final_status == "needs_review"
            assert "cv_download_failed" in (res.reason or "")
            mock_transition.assert_called_once()
            assert mock_transition.call_args[1]["to_status"] == "needs_review"

    asyncio.run(run())


def test_process_application_unsupported_platform_manual_apply(sample_claim):
    async def run():
        sample_claim.ats_platform = "workday"
        with (
            patch("jobs.apply.runner.check_posting_liveness", new_callable=AsyncMock) as mock_liveness,
            patch("jobs.apply.runner.download_resume_stream") as mock_download,
            patch("jobs.apply.runner.transition_application_status") as mock_transition,
        ):
            mock_liveness.return_value = True
            mock_download.return_value = io.BytesIO(b"%PDF-1.4 mock")

            res = await process_application(sample_claim)

            assert res.final_status == "manual_apply"
            assert "workday" in (res.reason or "")
            mock_transition.assert_called_once_with(
                application_id=101,
                to_status="manual_apply",
                from_status="submitting",
                reason="platform_workday_requires_manual_apply",
            )

    asyncio.run(run())


def test_process_application_greenhouse_ready_submitted(sample_claim):
    async def run():
        mock_submitter = MagicMock()
        mock_submitter.fetch_questions = AsyncMock(return_value=[])
        mock_submitter.map_and_validate_payload.return_value = SubmissionResult(
            status="ready",
            payload={"first_name": "Jane", "last_name": "Doe", "email": "jane@example.com"},
        )
        mock_submitter.submit = AsyncMock(
            return_value=SubmitResponse(
                status="submitted",
                external_application_id="APP-STRIPE-999",
            )
        )

        with (
            patch("jobs.apply.runner.check_posting_liveness", new_callable=AsyncMock) as mock_liveness,
            patch("jobs.apply.runner.download_resume_stream") as mock_download,
            patch("jobs.apply.runner.resolve_submitter", return_value=mock_submitter),
            patch("jobs.apply.runner.transition_application_status") as mock_transition,
        ):
            mock_liveness.return_value = True
            mock_download.return_value = io.BytesIO(b"%PDF-1.4 dummy pdf")

            res = await process_application(sample_claim)

            assert res.final_status == "submitted"
            assert res.confirmation_id == "APP-STRIPE-999"
            mock_transition.assert_called_once_with(
                application_id=101,
                to_status="submitted",
                from_status="submitting",
                reason="submission_successful",
                submitted_payload={
                    "submitted": True,
                    "confirmation_id": "APP-STRIPE-999",
                    "external_application_id": "APP-STRIPE-999",
                    "redirect_url": None,
                },
            )

    asyncio.run(run())


def test_process_application_dry_run_simulation(sample_claim):
    async def run():
        mock_submitter = MagicMock()
        mock_submitter.fetch_questions = AsyncMock(return_value=[])
        mock_submitter.map_and_validate_payload.return_value = SubmissionResult(
            status="ready",
            payload={"first_name": "Jane", "email": "jane@example.com"},
        )

        with (
            patch("jobs.apply.runner.check_posting_liveness", new_callable=AsyncMock) as mock_liveness,
            patch("jobs.apply.runner.download_resume_stream") as mock_download,
            patch("jobs.apply.runner.resolve_submitter", return_value=mock_submitter),
            patch("jobs.apply.runner.transition_application_status") as mock_transition,
        ):
            mock_liveness.return_value = True
            mock_download.return_value = io.BytesIO(b"%PDF-1.4 dummy pdf")

            res = await process_application(sample_claim, dry_run=True)

            assert res.final_status == "submitted"
            assert res.reason == "dry_run_simulation"
            mock_submitter.submit.assert_not_called()
            mock_transition.assert_called_once()
            assert mock_transition.call_args[1]["reason"] == "dry_run_simulation"

    asyncio.run(run())


def test_process_application_captcha_transitions_to_manual_apply(sample_claim):
    async def run():
        mock_submitter = MagicMock()
        mock_submitter.fetch_questions = AsyncMock(return_value=[])
        mock_submitter.map_and_validate_payload.return_value = SubmissionResult(
            status="manual_apply",
            reason="reCAPTCHA challenge required",
        )

        with (
            patch("jobs.apply.runner.check_posting_liveness", new_callable=AsyncMock) as mock_liveness,
            patch("jobs.apply.runner.download_resume_stream") as mock_download,
            patch("jobs.apply.runner.resolve_submitter", return_value=mock_submitter),
            patch("jobs.apply.runner.transition_application_status") as mock_transition,
        ):
            mock_liveness.return_value = True
            mock_download.return_value = io.BytesIO(b"%PDF-1.4 dummy pdf")

            res = await process_application(sample_claim)

            assert res.final_status == "manual_apply"
            assert res.reason == "reCAPTCHA challenge required"
            mock_transition.assert_called_once_with(
                application_id=101,
                to_status="manual_apply",
                from_status="submitting",
                reason="reCAPTCHA challenge required",
            )

    asyncio.run(run())


def test_process_application_unmapped_questions_transitions_to_needs_review(sample_claim):
    async def run():
        mock_submitter = MagicMock()
        mock_submitter.fetch_questions = AsyncMock(return_value=[])
        mock_submitter.map_and_validate_payload.return_value = SubmissionResult(
            status="needs_review",
            reason="Unmapped required question: Salary Expectations",
        )

        with (
            patch("jobs.apply.runner.check_posting_liveness", new_callable=AsyncMock) as mock_liveness,
            patch("jobs.apply.runner.download_resume_stream") as mock_download,
            patch("jobs.apply.runner.resolve_submitter", return_value=mock_submitter),
            patch("jobs.apply.runner.transition_application_status") as mock_transition,
        ):
            mock_liveness.return_value = True
            mock_download.return_value = io.BytesIO(b"%PDF-1.4 dummy pdf")

            res = await process_application(sample_claim)

            assert res.final_status == "needs_review"
            assert "Unmapped required question" in (res.reason or "")
            mock_transition.assert_called_once()
            assert mock_transition.call_args[1]["to_status"] == "needs_review"

    asyncio.run(run())


def test_process_application_network_error_schedules_retry(sample_claim):
    async def run():
        mock_submitter = MagicMock()
        mock_submitter.fetch_questions = AsyncMock(return_value=[])
        mock_submitter.map_and_validate_payload.return_value = SubmissionResult(
            status="ready",
            payload={"first_name": "Jane"},
        )
        mock_submitter.submit = AsyncMock(side_effect=httpx.ConnectTimeout("ATS endpoint timeout"))

        sample_claim.attempts = 1

        with (
            patch("jobs.apply.runner.check_posting_liveness", new_callable=AsyncMock) as mock_liveness,
            patch("jobs.apply.runner.download_resume_stream") as mock_download,
            patch("jobs.apply.runner.resolve_submitter", return_value=mock_submitter),
            patch("jobs.apply.runner.transition_application_status") as mock_transition,
        ):
            mock_liveness.return_value = True
            mock_download.return_value = io.BytesIO(b"%PDF-1.4 dummy pdf")

            res = await process_application(sample_claim)

            assert res.final_status == "queued"
            mock_transition.assert_called_once()
            assert mock_transition.call_args[1]["to_status"] == "queued"
            assert mock_transition.call_args[1]["next_attempt_at"] is not None

    asyncio.run(run())


def test_process_application_max_attempts_exceeded_fails(sample_claim):
    async def run():
        mock_submitter = MagicMock()
        mock_submitter.fetch_questions = AsyncMock(return_value=[])
        mock_submitter.map_and_validate_payload.return_value = SubmissionResult(
            status="ready",
            payload={"first_name": "Jane"},
        )
        mock_submitter.submit = AsyncMock(side_effect=httpx.ConnectTimeout("ATS endpoint timeout"))

        sample_claim.attempts = 3

        with (
            patch("jobs.apply.runner.check_posting_liveness", new_callable=AsyncMock) as mock_liveness,
            patch("jobs.apply.runner.download_resume_stream") as mock_download,
            patch("jobs.apply.runner.resolve_submitter", return_value=mock_submitter),
            patch("jobs.apply.runner.transition_application_status") as mock_transition,
        ):
            mock_liveness.return_value = True
            mock_download.return_value = io.BytesIO(b"%PDF-1.4 dummy pdf")

            res = await process_application(sample_claim)

            assert res.final_status == "failed"
            mock_transition.assert_called_once()
            assert mock_transition.call_args[1]["to_status"] == "failed"

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Crash Recovery Reaper & Worker Polling Loop
# ---------------------------------------------------------------------------


def test_reap_stuck_applications_delegates():
    with patch("jobs.apply.runner.reap_stalled_applications", return_value=4) as mock_reap:
        count = reap_stuck_applications(timeout_minutes=5)
        assert count == 4
        mock_reap.assert_called_once_with(stalled_threshold_seconds=300)


def test_run_queue_worker_processes_and_exits():
    async def run():
        claim_dict = {
            "id": 101,
            "user_id": 1,
            "job_posting_id": 501,
            "company_id": 20,
            "company_name": "Stripe",
            "ats_platform": "greenhouse",
            "ats_identifier": "stripe",
            "job_url": "https://boards.greenhouse.io/stripe/jobs/501",
            "job_title": "Backend Engineer",
            "attempt_token": "00000000-0000-0000-0000-000000000099",
            "attempts": 1,
            "screening_defaults": {"first_name": "Jane"},
            "resume_data": {},
            "resume_storage_path": "1/resume.pdf",
            "resume_filename": "resume.pdf",
            "resume_content_type": "application/pdf",
        }

        with (
            patch("jobs.apply.runner.claim_next_queued_application", side_effect=[claim_dict, None]),
            patch("jobs.apply.runner.process_application", new_callable=AsyncMock) as mock_process,
            patch("jobs.apply.runner.reap_stuck_applications", return_value=0),
        ):
            mock_process.return_value = ProcessingResult(application_id=101, final_status="submitted")

            processed = await run_queue_worker(poll_interval=0.01, max_iterations=2)

            assert processed == 1
            assert mock_process.call_count == 1
            claim_arg = mock_process.call_args[0][0]
            assert isinstance(claim_arg, ApplicationClaim)
            assert claim_arg.id == 101

    asyncio.run(run())
