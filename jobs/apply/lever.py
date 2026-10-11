"""Lever Postings API v0 job application submitter and question schema parser.

API Docs & Endpoints:
- GET https://api.lever.co/v0/postings/{company}/{id}?mode=json
- POST https://api.lever.co/v0/postings/{company}/{id} (multipart/form-data)
"""

from __future__ import annotations

import io
import logging
from typing import Any
from urllib.parse import urlparse

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
    get_candidate_url,
    map_screening_question,
)
from models import JobPosting, User

logger = logging.getLogger(__name__)


def extract_lever_identifiers(posting: JobPosting) -> tuple[str, str]:
    """Extract (company, job_id) from Lever posting record or URL."""
    job_id = str(posting.get("external_id") or "").strip()
    company = str(posting.get("ats_identifier") or "").strip()

    if company and job_id:
        return company, job_id

    url = posting.get("url") or ""
    if url:
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.strip("/").split("/") if p]
        # Example: https://jobs.lever.co/netflix/4b0e8e4a-... or https://api.lever.co/v0/postings/netflix/4b0e8e4a-...
        if "lever.co" in parsed.netloc:
            if "postings" in path_parts:
                idx = path_parts.index("postings")
                if len(path_parts) > idx + 2:
                    if not company:
                        company = path_parts[idx + 1]
                    if not job_id:
                        job_id = path_parts[idx + 2]
            elif len(path_parts) >= 2:
                if not company:
                    company = path_parts[0]
                if not job_id:
                    job_id = path_parts[1]

    return company, job_id


class LeverSubmitter(BaseSubmitter):
    """Submitter for Lever public job postings."""

    async def fetch_questions(self, posting: JobPosting) -> list[ScreeningQuestion]:
        """Fetch and parse live screening questions, custom cards, and consent fields for Lever posting."""
        company, job_id = extract_lever_identifiers(posting)
        if not company or not job_id:
            raise ValueError(f"Missing Lever company or job_id in posting: {posting.get('title')}")

        url = f"https://api.lever.co/v0/postings/{company}/{job_id}"
        params = {"mode": "json"}

        async def _fetch(cli: httpx.AsyncClient) -> httpx.Response:
            return await cli.get(url, params=params, timeout=15.0)

        if self.client:
            resp = await _fetch(self.client)
        else:
            async with httpx.AsyncClient() as cli:
                resp = await _fetch(cli)

        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            return []

        parsed_questions: list[ScreeningQuestion] = []

        # 1. Inspect custom questions / cards
        cards = data.get("cards") or []
        for card in cards:
            card_id = str(card.get("id") or "")
            card_title = (card.get("text") or card.get("title") or "").strip()
            fields = card.get("fields") or []

            if not fields:
                # Flat card format where card itself represents a question
                q_type_raw = card.get("type", "text")
                q_type = QuestionType.LONG_TEXT if q_type_raw == "textarea" else QuestionType.SHORT_TEXT
                options: list[QuestionOption] = []
                if q_type_raw in ("dropdown", "multiple-choice", "yes-no"):
                    q_type = QuestionType.SINGLE_SELECT
                    for opt in card.get("options") or []:
                        opt_id = opt.get("id") or opt.get("text")
                        options.append(QuestionOption(id=opt_id, label=opt.get("text", str(opt_id))))

                parsed_questions.append(
                    ScreeningQuestion(
                        id=card_id,
                        label=card_title,
                        question_type=q_type,
                        required=bool(card.get("required", False)),
                        options=options,
                        raw_field_name=f"cards[{card_id}]",
                    )
                )
                continue

            for fld in fields:
                fld_id = str(fld.get("id") or "")
                fld_text = (fld.get("text") or fld.get("title") or card_title).strip()
                fld_type_raw = fld.get("type", "text")
                required = bool(fld.get("required", False))

                q_type = QuestionType.SHORT_TEXT
                options = []
                if fld_type_raw == "textarea":
                    q_type = QuestionType.LONG_TEXT
                elif fld_type_raw in ("dropdown", "multiple-choice", "yes-no"):
                    q_type = QuestionType.SINGLE_SELECT
                    for opt in fld.get("options") or []:
                        opt_id = opt.get("id") or opt.get("text")
                        options.append(QuestionOption(id=opt_id, label=opt.get("text", str(opt_id))))
                elif fld_type_raw == "boolean":
                    q_type = QuestionType.BOOLEAN

                composite_id = f"{card_id}_{fld_id}" if fld_id else card_id
                field_name = f"cards[{card_id}][{fld_id}]" if fld_id else f"cards[{card_id}]"

                parsed_questions.append(
                    ScreeningQuestion(
                        id=composite_id,
                        label=fld_text,
                        question_type=q_type,
                        required=required,
                        options=options,
                        raw_field_name=field_name,
                    )
                )

        # 2. Inspect custom questions array if present outside cards
        custom_questions = data.get("customQuestions") or []
        for cq in custom_questions:
            cq_id = str(cq.get("id") or "")
            cq_title = (cq.get("text") or cq.get("title") or "").strip()
            cq_type_raw = cq.get("type", "text")
            options = []
            if cq_type_raw in ("dropdown", "multiple-choice", "yes-no"):
                q_type = QuestionType.SINGLE_SELECT
                for opt in cq.get("options") or []:
                    opt_id = opt.get("id") or opt.get("text")
                    options.append(QuestionOption(id=opt_id, label=opt.get("text", str(opt_id))))
            elif cq_type_raw == "textarea":
                q_type = QuestionType.LONG_TEXT
            else:
                q_type = QuestionType.SHORT_TEXT

            parsed_questions.append(
                ScreeningQuestion(
                    id=cq_id,
                    label=cq_title,
                    question_type=q_type,
                    required=bool(cq.get("required", False)),
                    options=options,
                    raw_field_name=f"customQuestions[{cq_id}]",
                )
            )

        return parsed_questions

    def map_and_validate_payload(
        self,
        user: User,
        posting: JobPosting,
        questions: list[ScreeningQuestion],
    ) -> SubmissionResult:
        """Map user profile into Lever multipart parameters and evaluate question confidence."""
        full_name, _, _ = get_candidate_names(user)
        email = user.get("email") or ""
        phone = get_candidate_phone(user)

        resume_data = user.get("resume_data") or {}
        current_org = str(resume_data.get("current_company") or resume_data.get("organization") or "").strip()

        payload: dict[str, Any] = {
            "name": full_name,
            "email": email,
            "phone": phone,
            "consent[data-retention]": "true",
        }
        if current_org:
            payload["org"] = current_org

        # Profile URLs
        for plat, key in (
            ("linkedin", "urls[LinkedIn]"),
            ("github", "urls[GitHub]"),
            ("portfolio", "urls[Portfolio]"),
            ("twitter", "urls[Twitter]"),
        ):
            url = get_candidate_url(user, plat)
            if url:
                payload[key] = url

        unmapped: list[ScreeningQuestion] = []
        has_captcha = False

        for q in questions:
            field_name = q.raw_field_name or f"cards[{q.id}]"
            clean_label = q.label.lower()

            if "captcha" in field_name.lower() or "captcha" in clean_label:
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
        """Submit multipart form application to Lever Postings API."""
        company, job_id = extract_lever_identifiers(posting)
        if not company or not job_id:
            return SubmitResponse(
                status="failed",
                reason="missing_identifiers",
                error_message="Could not resolve Lever company or job_id",
            )

        url = f"https://api.lever.co/v0/postings/{company}/{job_id}"
        resume_bytes = resume_stream.getvalue()
        files = {
            "resume": (filename, resume_bytes, content_type),
        }

        data: dict[str, Any] = {}
        for k, v in payload.items():
            if isinstance(v, bool):
                data[k] = "true" if v else "false"
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
            logger.warning("Network error submitting to Lever: %s", exc)
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
            app_id = res_data.get("applicationId") or res_data.get("id")
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
                reason="posting_closed",
                http_status=404,
                error_message="Job posting no longer exists on Lever portal",
            )

        resp_text = resp.text.lower()
        if resp.status_code in (400, 422):
            if any(term in resp_text for term in ("captcha", "recaptcha", "robot", "turnstile", "hcaptcha")):
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
