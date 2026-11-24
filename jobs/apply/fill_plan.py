"""Fill plans for the remote-browser apply spike (#129).

For allowlisted users only, the pipeline reads each Greenhouse To Apply posting's public question schema and
stores which answers the user's profile gives confidently. The web app fills the employer's form from it; the
user always reviews and clicks Submit. Nothing here submits anything.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlencode

import httpx

from db import queries
from jobs.apply.base import QuestionType, ScreeningQuestion, map_screening_question
from jobs.apply.greenhouse import GreenhouseSubmitter, extract_greenhouse_identifiers
from models import JobPosting, User

logger = logging.getLogger(__name__)

PLAN_VERSION = 1
# Filled by the web app from the profile at fill time, so they can change after the plan is built.
STANDARD_LABELS = {"first name", "last name", "email", "phone", "resume", "resume/cv", "cover letter"}


def allowlisted_user_ids(raw: str | None = None) -> set[int]:
    """REMOTE_APPLY_USER_IDS, e.g. "3,7". Empty or unset means the spike is off."""
    raw = os.environ.get("REMOTE_APPLY_USER_IDS", "") if raw is None else raw
    return {int(part) for part in raw.split(",") if part.strip().isdigit()}


def greenhouse_form_url(posting: JobPosting) -> str | None:
    """The bare application form. Hosted board pages of some employers (Databricks, Datadog) redirect to their own
    careers site, where the form sits in an iframe; the embed URL serves the form itself (Task 3.4, 2026-11-23)."""
    board_token, job_id = extract_greenhouse_identifiers(posting)
    if not (board_token and job_id):
        return None
    return f"https://job-boards.greenhouse.io/embed/job_app?{urlencode({'for': board_token, 'token': job_id})}"


def build_plan(questions: list[ScreeningQuestion], user: User, posting_url: str | None) -> dict[str, Any]:
    """Confident answers go in `fields`; open-ended and unanswered required questions go in `for_user`."""
    fields: list[dict[str, Any]] = []
    for_user: list[dict[str, Any]] = []
    for q in questions:
        name = q.raw_field_name or f"question_{q.id}"
        label = q.label.strip()
        if "recaptcha" in name.lower() or label.lower() in STANDARD_LABELS:
            continue
        if q.question_type == QuestionType.FILE:
            if q.required:
                for_user.append({"name": name, "label": label, "reason": "file"})
            continue
        if q.question_type == QuestionType.LONG_TEXT or len(label) > 100:
            for_user.append({"name": name, "label": label, "reason": "open_ended"})
            continue
        value, confident = map_screening_question(q, user)
        if confident and value is not None:
            field: dict[str, Any] = {"name": name, "label": label, "type": q.question_type.value, "value": value}
            option = next((o for o in q.options if o.id == value), None)
            if option:
                field["option_label"] = option.label  # forms show labels; the API value may be an id
            fields.append(field)
        elif q.required:
            for_user.append({"name": name, "label": label, "reason": "no_confident_answer"})
    return {
        "version": PLAN_VERSION,
        "platform": "greenhouse",
        "posting_url": posting_url,
        "fields": fields,
        "for_user": for_user,
    }


async def build_fill_plans(users: list[User], client: httpx.AsyncClient | None = None) -> int:
    """Build or refresh plans for allowlisted users' Greenhouse To Apply rows. Returns plans written.

    One posting at a time: a handful of users, and no DB connection is held during the GETs.
    """
    allowed = allowlisted_user_ids()
    by_id = {u["id"]: u for u in users if u.get("id") in allowed}
    if not by_id:
        return 0
    submitter = GreenhouseSubmitter(client)
    written = 0
    for cand in queries.list_fill_plan_candidates(sorted(by_id)):
        posting = cand["posting"]
        try:
            questions = await submitter.fetch_questions(posting)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                logger.warning("Fill plan: questions for application %s: %s", cand["application_id"], exc)
            continue  # a closed posting is left for the pipeline's 30-day closing
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Fill plan: questions for application %s: %s", cand["application_id"], exc)
            continue
        queries.upsert_fill_plan(
            cand["application_id"], build_plan(questions, by_id[cand["user_id"]], greenhouse_form_url(posting))
        )
        written += 1
    return written
