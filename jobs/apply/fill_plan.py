"""Fill plans for the remote-browser apply spike (#129).

For allowlisted users only, the pipeline reads each Greenhouse To Apply posting's public question schema and
stores which answers the user's profile gives confidently. The web app fills the employer's form from it; the
user always reviews and clicks Submit. Nothing here submits anything.

Users who opted in also get Groq drafts for open-ended questions, grounded in their CV (#59).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, cast
from urllib.parse import urlencode

import httpx

from db import queries
from jobs.apply import llm_answers
from jobs.apply.base import QuestionType, ScreeningQuestion, map_screening_question
from jobs.apply.cv_security import validate_cv
from jobs.apply.cv_storage import download_resume_stream
from jobs.apply.greenhouse import GreenhouseSubmitter, extract_greenhouse_identifiers
from models import JobPosting, User
from scrapers.base import strip_html

logger = logging.getLogger(__name__)

PLAN_VERSION = 1
# Filled by the web app from the profile at fill time, so they can change after the plan is built.
STANDARD_LABELS = {"first name", "last name", "email", "phone", "resume", "resume/cv", "cover letter"}
# Free-text questions only: selects and checkboxes need facts, not prose.
DRAFTABLE = {QuestionType.LONG_TEXT.value, QuestionType.SHORT_TEXT.value}
MEMORY_CAP = 200  # saved questions per user (answer memory)


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
            for_user.append({"name": name, "label": label, "reason": "open_ended", "type": q.question_type.value})
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


def _load_cv_text(user: User) -> str | None:
    """CV text from storage, in memory only. None when there is no usable CV; never raises."""
    path = user.get("resume_storage_path")
    if not path:
        return None
    try:
        stream, filename, _ = download_resume_stream(path, owner_id=user["auth_user_id"])
    except Exception as exc:  # storage, network or path errors: the plan is still written, without new drafts
        logger.warning("Drafts: CV download for user %s failed: %s", user.get("id"), type(exc).__name__)
        return None
    data = stream.getvalue()
    ok, error = validate_cv(data, filename)
    if not ok:
        logger.warning("Drafts: CV of user %s refused: %s", user.get("id"), error)
        return None
    text = llm_answers.extract_cv_text(data, filename)
    if text is None:
        logger.warning("Drafts: no usable text in the CV of user %s (.doc, scanned or unreadable)", user.get("id"))
    return text


class Drafter:
    """Groq drafting for one build_fill_plans run: the client, the circuit breaker, and CV text per user."""

    def __init__(self, client: httpx.AsyncClient, api_key: str | None = None, model: str | None = None):
        self.client = client
        self.api_key = os.environ.get("GROQ_API_KEY", "") if api_key is None else api_key
        self.model = model or os.environ.get("GROQ_MODEL") or llm_answers.DEFAULT_MODEL
        self.tripped = False  # set by the first question that fails: no more Groq calls this run
        self.memory_full: set[object] = set()  # users already told their answer memory is full this run
        self._cv: dict[object, str | None] = {}

    async def cv_text(self, user: User) -> str | None:
        key = user.get("id")
        if key not in self._cv:
            self._cv[key] = await asyncio.to_thread(_load_cv_text, user)  # sync HTTP; once per user per run
        return self._cv[key]


def keep_skipped(plan: dict[str, Any], previous_plan: dict[str, Any] | None) -> None:
    """Open-ended questions Groq answered SKIP before stay personal-fact (`no_confident_answer`) entries, in place.

    Needs no Groq call, so it runs whether or not the user drafts; otherwise their saved answers would stop being used.
    """
    skipped = {
        (e.get("name"), e.get("label"))
        for e in (previous_plan or {}).get("for_user", [])
        if e.get("reason") == "no_confident_answer"
    }
    for entry in plan["for_user"]:
        if entry["reason"] == "open_ended" and (entry["name"], entry["label"]) in skipped:
            entry["reason"] = "no_confident_answer"


async def add_drafts(
    plan: dict[str, Any], previous_plan: dict[str, Any] | None, user: User, job_description: str, drafter: Drafter
) -> None:
    """Give the plan's open-ended free-text questions a draft, in place.

    A generated draft from the previous plan for the same question is kept, with no Groq call. The CV is read only
    when a new draft is needed. A question Groq answered SKIP (only the candidate can answer it) becomes a
    `no_confident_answer` entry for the answer memory, and stays one on refresh (`keep_skipped`). After a
    failure the entry is `unanswered` and the run's breaker trips; entries after it get no draft fields and are
    tried on the next run.
    """
    keep_skipped(plan, previous_plan)
    previous = {(e.get("name"), e.get("label")): e for e in (previous_plan or {}).get("for_user", [])}
    for entry in plan["for_user"]:
        if entry["reason"] != "open_ended" or entry.get("type") not in DRAFTABLE:
            continue
        old = previous.get((entry["name"], entry["label"]), {})
        if old.get("draft_status") == "generated" and old.get("draft"):
            entry.update(draft=old["draft"], draft_status="generated")
            continue
        if drafter.tripped:
            continue
        cv_text = await drafter.cv_text(user)
        if not cv_text:
            continue
        draft, reason = await llm_answers.draft_open_question_answer(
            drafter.client, entry["label"], job_description, cv_text, api_key=drafter.api_key, model=drafter.model
        )
        if draft:
            entry.update(draft=draft, draft_status="generated")
        elif reason == "skip":
            entry["reason"] = "no_confident_answer"
        else:
            entry.update(draft_status="unanswered", draft_reason=reason)
            drafter.tripped = True


async def add_memory_links(
    plan: dict[str, Any],
    previous_plan: dict[str, Any] | None,
    saved: list[dict],
    drafter: Drafter,
    use_groq: bool,
    user_id: object,
) -> list[dict]:
    """Link the plan's personal-fact questions to saved ones, in place. Returns new pending questions to save.

    A link from the previous plan is kept while its saved row exists. Otherwise the same normalized text links as
    `exact`; then, with `use_groq`, Groq may name a saved question asking the same thing (`similar`). Only question
    texts go to Groq. Unmatched questions come back once per key as {question, question_key}, up to MEMORY_CAP.
    """
    ids = {s["id"] for s in saved}
    by_key = {s["question_key"]: s for s in saved}
    kept = {
        (e.get("name"), e.get("label")): e
        for e in (previous_plan or {}).get("for_user", [])
        if e.get("memory_id") in ids
    }
    new: list[dict] = []
    for entry in plan["for_user"]:
        if entry["reason"] != "no_confident_answer":
            continue
        key = llm_answers.normalize_question(entry["label"])
        if not key:
            continue
        if key in by_key:  # an exact match beats a link kept from the previous plan
            entry.update(memory_id=by_key[key]["id"], memory_match="exact")
            continue
        old = kept.get((entry["name"], entry["label"]))
        if old:
            entry.update(memory_id=old["memory_id"], memory_match=old.get("memory_match", "exact"))
            continue
        if any(n["question_key"] == key for n in new):
            continue
        if use_groq and saved and not drafter.tripped:
            index, reason = await llm_answers.match_saved_question(
                drafter.client,
                entry["label"],
                [s["question"] for s in saved],
                api_key=drafter.api_key,
                model=drafter.model,
            )
            if index is not None:
                entry.update(memory_id=saved[index]["id"], memory_match="similar")
                continue
            if reason:
                drafter.tripped = True  # still saved as pending below
        if len(saved) + len(new) >= MEMORY_CAP:
            if user_id not in drafter.memory_full:
                drafter.memory_full.add(user_id)
                logger.warning(
                    "Answer memory of user %s is full (%d questions): new ones are not saved", user_id, MEMORY_CAP
                )
            continue
        new.append({"question": entry["label"][:500], "question_key": key})
    return new


async def build_fill_plans(users: list[User], client: httpx.AsyncClient | None = None) -> int:
    """Build or refresh plans for allowlisted users' Greenhouse To Apply rows. Returns plans written.

    One posting at a time: a handful of users, and no DB connection is held during the GETs.
    """
    allowed = allowlisted_user_ids()
    by_id = {u["id"]: u for u in users if u.get("id") in allowed}
    if not by_id:
        return 0
    if client is None:
        async with httpx.AsyncClient() as owned:
            return await build_fill_plans(users, owned)
    submitter = GreenhouseSubmitter(client)
    drafter = Drafter(client)
    if not drafter.api_key and any(u.get("llm_drafts_enabled") for u in by_id.values()):
        logger.warning("Drafts: GROQ_API_KEY is not set, so no open-ended answers are drafted this run")
    try:
        memory: dict[int, list[dict]] | None = queries.get_user_answers(sorted(by_id))
    except Exception as exc:  # e.g. user_answers not created yet: plans are still built, without memory
        logger.warning("Answer memory unavailable this run: %s", type(exc).__name__)
        memory = None
    written = 0
    for cand in queries.list_fill_plan_candidates(sorted(by_id)):
        posting = cand["posting"]
        try:
            job = await submitter.fetch_job(posting)
            questions = submitter.parse_questions(job)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                logger.warning("Fill plan: questions for application %s: %s", cand["application_id"], exc)
            continue  # a closed posting is left for the pipeline's 30-day closing
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Fill plan: questions for application %s: %s", cand["application_id"], exc)
            continue
        user = by_id[cand["user_id"]]
        plan = build_plan(questions, user, greenhouse_form_url(posting))
        if user.get("llm_drafts_enabled") and user.get("resume_storage_path") and drafter.api_key:
            try:
                await add_drafts(plan, cand.get("previous_plan"), user, strip_html(job.get("content")) or "", drafter)
            except Exception as exc:  # drafting must never cost the user their plan
                logger.warning("Drafts for application %s failed: %s", cand["application_id"], type(exc).__name__)
        else:
            keep_skipped(plan, cand.get("previous_plan"))
        if memory is not None:
            try:
                saved = memory.setdefault(user["id"], [])
                use_groq = bool(user.get("llm_drafts_enabled") and drafter.api_key)
                new = await add_memory_links(plan, cand.get("previous_plan"), saved, drafter, use_groq, user["id"])
                saved.extend(queries.add_pending_questions(user["id"], new))
            except Exception as exc:  # the answer memory must never cost the user their plan
                logger.warning(
                    "Answer memory for application %s failed: %s", cand["application_id"], type(exc).__name__
                )
        queries.upsert_fill_plan(cand["application_id"], plan)
        written += 1
    return written


def main() -> int:
    """`python -m jobs.apply.fill_plan`: build plans in their own digest.yml step, the only one given the Groq and
    Supabase service-role keys. The scrape step has no allowlist, so its own call to build_fill_plans is skipped."""
    from config import setup_logging

    setup_logging()
    users = cast(list[User], queries.get_active_users())  # rows are User-shaped dicts
    logger.info("Built %d fill plan(s).", asyncio.run(build_fill_plans(users)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
