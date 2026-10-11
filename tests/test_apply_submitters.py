"""Unit tests for ATS submitters (Base, Greenhouse, Lever, and ManualApply).

Tests question schema parsing, profile mapping heuristics, multipart form assembly,
and error/captcha classification using in-memory mock transports.
"""

from __future__ import annotations

import asyncio
import io

import httpx
import pytest

from jobs.apply import (
    GreenhouseSubmitter,
    LeverSubmitter,
    ManualApplySubmitter,
    QuestionOption,
    QuestionType,
    ScreeningQuestion,
    get_candidate_names,
    get_candidate_phone,
    get_submitter,
    map_screening_question,
)
from models import JobPosting, User


@pytest.fixture
def sample_user() -> User:
    return {
        "id": 1,
        "auth_user_id": "00000000-0000-0000-0000-000000000001",
        "email": "jane.doe@example.com",
        "resume_data": {
            "first_name": "Jane",
            "last_name": "Doe",
            "phone": "+1-555-0199",
            "location": "San Francisco, CA",
            "current_company": "Acme Corp",
            "urls": {
                "linkedin": "https://linkedin.com/in/janedoe",
                "github": "https://github.com/janedoe",
                "portfolio": "https://janedoe.dev",
                "twitter": "https://x.com/janedoe",
            },
        },
        "profile_filters": {"titles": ["Software Engineer"]},
        "screening_defaults": {
            "work_authorization": True,
            "requires_sponsorship": False,
            "years_experience": 5,
            "notice_period_days": 30,
            "current_location": "San Francisco, CA",
        },
        "gdpr_consent_at": "2026-10-11T12:00:00Z",
    }


@pytest.fixture
def sample_greenhouse_posting() -> JobPosting:
    return {
        "external_id": "123456",
        "title": "Senior Backend Engineer",
        "location": "San Francisco, CA",
        "department": "Engineering",
        "url": "https://boards.greenhouse.io/stripe/jobs/123456",
        "description": "Build high scale APIs.",
        "ats_identifier": "stripe",
        "ats_platform": "greenhouse",
    }


@pytest.fixture
def sample_lever_posting() -> JobPosting:
    return {
        "external_id": "4b0e8e4a-1111-2222-3333-444455556666",
        "title": "Infrastructure Engineer",
        "location": "Remote",
        "department": "Infrastructure",
        "url": "https://jobs.lever.co/netflix/4b0e8e4a-1111-2222-3333-444455556666",
        "description": "Cloud platform systems.",
        "ats_identifier": "netflix",
        "ats_platform": "lever",
    }


# ============================================================================
# 1. Base Mapping & Helper Tests
# ============================================================================


def test_get_candidate_names_explicit(sample_user: User):
    full, first, last = get_candidate_names(sample_user)
    assert full == "Jane Doe"
    assert first == "Jane"
    assert last == "Doe"


def test_get_candidate_names_from_full_name():
    user: User = {
        "auth_user_id": "u1",
        "email": "test@example.com",
        "resume_data": {"full_name": "Alex Smith"},
        "profile_filters": {},
        "screening_defaults": {},
        "gdpr_consent_at": "2026-01-01T00:00:00Z",
    }
    full, first, last = get_candidate_names(user)
    assert full == "Alex Smith"
    assert first == "Alex"
    assert last == "Smith"


def test_get_candidate_names_from_email_fallback():
    user: User = {
        "auth_user_id": "u1",
        "email": "john.watson@example.com",
        "resume_data": {},
        "profile_filters": {},
        "screening_defaults": {},
        "gdpr_consent_at": "2026-01-01T00:00:00Z",
    }
    full, first, last = get_candidate_names(user)
    assert full == "John Watson"
    assert first == "John"
    assert last == "Watson"


def test_get_candidate_phone(sample_user: User):
    assert get_candidate_phone(sample_user) == "+1-555-0199"


def test_map_work_authorization_boolean(sample_user: User):
    q = ScreeningQuestion(
        id=1,
        label="Are you legally authorized to work in the United States?",
        question_type=QuestionType.BOOLEAN,
        required=True,
    )
    val, confident = map_screening_question(q, sample_user)
    assert confident is True
    assert val is True


def test_map_work_authorization_select(sample_user: User):
    q = ScreeningQuestion(
        id=2,
        label="Legal right to work in the US",
        question_type=QuestionType.SINGLE_SELECT,
        required=True,
        options=[
            QuestionOption(id="opt_yes", label="Yes, I am authorized"),
            QuestionOption(id="opt_no", label="No, I am not"),
        ],
    )
    val, confident = map_screening_question(q, sample_user)
    assert confident is True
    assert val == "opt_yes"


def test_map_visa_sponsorship(sample_user: User):
    q = ScreeningQuestion(
        id=3,
        label="Will you now or in the future require visa sponsorship?",
        question_type=QuestionType.SINGLE_SELECT,
        required=True,
        options=[
            QuestionOption(id="sp_yes", label="Yes"),
            QuestionOption(id="sp_no", label="No"),
        ],
    )
    val, confident = map_screening_question(q, sample_user)
    assert confident is True
    assert val == "sp_no"


def test_map_years_of_experience(sample_user: User):
    q = ScreeningQuestion(
        id=4,
        label="How many years of relevant software engineering experience do you have?",
        question_type=QuestionType.SINGLE_SELECT,
        required=True,
        options=[
            QuestionOption(id="y1", label="0-2 years"),
            QuestionOption(id="y2", label="3-5 years"),
            QuestionOption(id="y3", label="6+ years"),
        ],
    )
    val, confident = map_screening_question(q, sample_user)
    assert confident is True
    assert val == "y2"


def test_map_notice_period(sample_user: User):
    q = ScreeningQuestion(
        id=5,
        label="What is your current notice period?",
        question_type=QuestionType.SHORT_TEXT,
        required=True,
    )
    val, confident = map_screening_question(q, sample_user)
    assert confident is True
    assert val == "30 days"


def test_map_open_ended_essay_fails_confidence(sample_user: User):
    q = ScreeningQuestion(
        id=6,
        label="Why do you want to join our engineering organization, and what was your most challenging bug?",
        question_type=QuestionType.LONG_TEXT,
        required=True,
    )
    val, confident = map_screening_question(q, sample_user)
    assert confident is False
    assert val is None


def test_map_unmapped_question_fails_confidence(sample_user: User):
    q = ScreeningQuestion(
        id=7,
        label="What is your favorite distributed database?",
        question_type=QuestionType.SHORT_TEXT,
        required=True,
    )
    val, confident = map_screening_question(q, sample_user)
    assert confident is False
    assert val is None


# ============================================================================
# 2. Factory & Fallback Submitter Tests
# ============================================================================


def test_get_submitter_factory():
    assert isinstance(get_submitter("greenhouse"), GreenhouseSubmitter)
    assert isinstance(get_submitter("lever"), LeverSubmitter)
    assert isinstance(get_submitter("ashby"), ManualApplySubmitter)
    assert isinstance(get_submitter("smartrecruiters"), ManualApplySubmitter)
    assert isinstance(get_submitter("workday"), ManualApplySubmitter)


def test_manual_apply_submitter(sample_user: User):
    async def run():
        posting: JobPosting = {
            "external_id": "ashby-123",
            "title": "Staff Engineer",
            "location": "Remote",
            "department": "Platform",
            "url": "https://jobs.ashbyhq.com/example/123",
            "description": "Ashby job.",
            "ats_platform": "ashby",
        }
        submitter = ManualApplySubmitter()
        questions = await submitter.fetch_questions(posting)
        assert questions == []

        preview = submitter.map_and_validate_payload(sample_user, posting, questions)
        assert preview.status == "manual_apply"
        assert "ashby" in str(preview.reason).lower()

        stream = io.BytesIO(b"%PDF-mock")
        resp = await submitter.submit(sample_user, posting, {}, stream, "resume.pdf")
        assert resp.status == "manual_apply"
        assert resp.redirect_url == "https://jobs.ashbyhq.com/example/123"

    asyncio.run(run())


# ============================================================================
# 3. Greenhouse Submitter Tests
# ============================================================================


SAMPLE_GH_JOB_QUESTIONS = {
    "id": 123456,
    "title": "Senior Backend Engineer",
    "questions": [
        {
            "id": 101,
            "label": "First Name",
            "required": True,
            "fields": [{"name": "first_name", "type": "input_text"}],
        },
        {
            "id": 102,
            "label": "Last Name",
            "required": True,
            "fields": [{"name": "last_name", "type": "input_text"}],
        },
        {
            "id": 103,
            "label": "Email",
            "required": True,
            "fields": [{"name": "email", "type": "input_text"}],
        },
        {
            "id": 104,
            "label": "Are you legally authorized to work in the United States?",
            "required": True,
            "fields": [
                {
                    "name": "question_104",
                    "type": "multi_value_single_select",
                    "values": [{"id": 1, "value": "Yes"}, {"id": 2, "value": "No"}],
                }
            ],
        },
        {
            "id": 105,
            "label": "Will you now or in the future require visa sponsorship?",
            "required": True,
            "fields": [
                {
                    "name": "question_105",
                    "type": "multi_value_single_select",
                    "values": [{"id": 3, "value": "Yes"}, {"id": 4, "value": "No"}],
                }
            ],
        },
    ],
}


def test_greenhouse_fetch_questions(sample_greenhouse_posting: JobPosting):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/boards/stripe/jobs/123456"
        assert request.url.params.get("questions") == "true"
        return httpx.Response(200, json=SAMPLE_GH_JOB_QUESTIONS)

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            submitter = GreenhouseSubmitter(client=http)
            return await submitter.fetch_questions(sample_greenhouse_posting)

    questions = asyncio.run(run())
    assert len(questions) == 5
    q_auth = questions[3]
    assert q_auth.id == 104
    assert q_auth.question_type == QuestionType.SINGLE_SELECT
    assert len(q_auth.options) == 2


def test_greenhouse_map_payload_success(sample_user: User, sample_greenhouse_posting: JobPosting):
    submitter = GreenhouseSubmitter()
    questions = [
        ScreeningQuestion(
            id=104,
            label="Are you legally authorized to work in the United States?",
            question_type=QuestionType.SINGLE_SELECT,
            required=True,
            raw_field_name="question_104",
            options=[QuestionOption(id="1", label="Yes"), QuestionOption(id="2", label="No")],
        ),
        ScreeningQuestion(
            id=105,
            label="Will you now or in the future require visa sponsorship?",
            question_type=QuestionType.SINGLE_SELECT,
            required=True,
            raw_field_name="question_105",
            options=[QuestionOption(id="3", label="Yes"), QuestionOption(id="4", label="No")],
        ),
    ]

    res = submitter.map_and_validate_payload(sample_user, sample_greenhouse_posting, questions)
    assert res.status == "ready"
    assert res.payload["first_name"] == "Jane"
    assert res.payload["last_name"] == "Doe"
    assert res.payload["email"] == "jane.doe@example.com"
    assert res.payload["phone"] == "+1-555-0199"
    assert res.payload["question_104"] == "1"
    assert res.payload["question_105"] == "4"
    assert res.unmapped_questions == []


def test_greenhouse_map_payload_unmapped_required(sample_user: User, sample_greenhouse_posting: JobPosting):
    submitter = GreenhouseSubmitter()
    questions = [
        ScreeningQuestion(
            id=999,
            label="Please write an essay describing your favorite distributed consensus algorithm.",
            question_type=QuestionType.LONG_TEXT,
            required=True,
            raw_field_name="question_999",
        )
    ]
    res = submitter.map_and_validate_payload(sample_user, sample_greenhouse_posting, questions)
    assert res.status == "needs_review"
    assert len(res.unmapped_questions) == 1
    assert res.unmapped_questions[0].id == 999


def test_greenhouse_map_payload_captcha_detected(sample_user: User, sample_greenhouse_posting: JobPosting):
    submitter = GreenhouseSubmitter()
    questions = [
        ScreeningQuestion(
            id=888,
            label="reCAPTCHA challenge",
            question_type=QuestionType.SHORT_TEXT,
            required=True,
            raw_field_name="g-recaptcha-response",
        )
    ]
    res = submitter.map_and_validate_payload(sample_user, sample_greenhouse_posting, questions)
    assert res.status == "manual_apply"
    assert res.reason == "captcha_blocked"


def test_greenhouse_submit_success(sample_user: User, sample_greenhouse_posting: JobPosting):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/boards/stripe/jobs/123456"
        assert request.method == "POST"
        assert "multipart/form-data" in request.headers.get("content-type", "")
        body = request.read().decode("latin1")
        assert 'name="resume"' in body
        assert 'name="first_name"' in body
        assert "Jane" in body
        return httpx.Response(200, json={"id": 987654, "redirect": "https://boards.greenhouse.io/stripe/thanks"})

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            submitter = GreenhouseSubmitter(client=http)
            payload = {"first_name": "Jane", "last_name": "Doe", "email": "jane@example.com"}
            stream = io.BytesIO(b"%PDF-mock-resume-bytes")
            return await submitter.submit(
                sample_user, sample_greenhouse_posting, payload, stream, "Jane_Doe_Resume.pdf"
            )

    resp = asyncio.run(run())
    assert resp.status == "submitted"
    assert resp.external_application_id == "987654"
    assert resp.redirect_url == "https://boards.greenhouse.io/stripe/thanks"


def test_greenhouse_submit_captcha_fallback(sample_user: User, sample_greenhouse_posting: JobPosting):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "Captcha verification is required for this board"})

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            submitter = GreenhouseSubmitter(client=http)
            stream = io.BytesIO(b"%PDF-mock")
            return await submitter.submit(sample_user, sample_greenhouse_posting, {}, stream, "resume.pdf")

    resp = asyncio.run(run())
    assert resp.status == "manual_apply"
    assert resp.reason == "captcha_blocked"


def test_greenhouse_submit_404_closed(sample_user: User, sample_greenhouse_posting: JobPosting):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="Job not found")

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            submitter = GreenhouseSubmitter(client=http)
            stream = io.BytesIO(b"%PDF-mock")
            return await submitter.submit(sample_user, sample_greenhouse_posting, {}, stream, "resume.pdf")

    resp = asyncio.run(run())
    assert resp.status == "stale_closed"
    assert resp.reason == "job_closed"


def test_greenhouse_preview_submission(sample_user: User, sample_greenhouse_posting: JobPosting):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SAMPLE_GH_JOB_QUESTIONS)

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            submitter = GreenhouseSubmitter(client=http)
            return await submitter.preview_submission(sample_user, sample_greenhouse_posting)

    preview = asyncio.run(run())
    assert preview.status == "ready"
    assert preview.payload["first_name"] == "Jane"


# ============================================================================
# 4. Lever Submitter Tests
# ============================================================================


SAMPLE_LEVER_JOB_DATA = {
    "id": "4b0e8e4a-1111-2222-3333-444455556666",
    "text": "Infrastructure Engineer",
    "cards": [
        {
            "id": "card_auth",
            "text": "Work Eligibility",
            "fields": [
                {
                    "id": "fld_1",
                    "text": "Are you legally authorized to work in the US?",
                    "type": "dropdown",
                    "required": True,
                    "options": [{"id": "yes", "text": "Yes"}, {"id": "no", "text": "No"}],
                }
            ],
        },
        {
            "id": "card_spon",
            "text": "Sponsorship Status",
            "fields": [
                {
                    "id": "fld_2",
                    "text": "Will you require visa sponsorship?",
                    "type": "dropdown",
                    "required": True,
                    "options": [{"id": "sp_yes", "text": "Yes"}, {"id": "sp_no", "text": "No"}],
                }
            ],
        },
    ],
}


def test_lever_fetch_questions(sample_lever_posting: JobPosting):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v0/postings/netflix/4b0e8e4a-1111-2222-3333-444455556666"
        assert request.url.params.get("mode") == "json"
        return httpx.Response(200, json=SAMPLE_LEVER_JOB_DATA)

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            submitter = LeverSubmitter(client=http)
            return await submitter.fetch_questions(sample_lever_posting)

    questions = asyncio.run(run())
    assert len(questions) == 2
    assert questions[0].raw_field_name == "cards[card_auth][fld_1]"
    assert questions[0].required is True
    assert len(questions[0].options) == 2


def test_lever_map_payload_success(sample_user: User, sample_lever_posting: JobPosting):
    submitter = LeverSubmitter()
    questions = [
        ScreeningQuestion(
            id="card_auth_fld_1",
            label="Are you legally authorized to work in the US?",
            question_type=QuestionType.SINGLE_SELECT,
            required=True,
            raw_field_name="cards[card_auth][fld_1]",
            options=[QuestionOption(id="yes", label="Yes"), QuestionOption(id="no", label="No")],
        )
    ]
    res = submitter.map_and_validate_payload(sample_user, sample_lever_posting, questions)
    assert res.status == "ready"
    assert res.payload["name"] == "Jane Doe"
    assert res.payload["email"] == "jane.doe@example.com"
    assert res.payload["phone"] == "+1-555-0199"
    assert res.payload["org"] == "Acme Corp"
    assert res.payload["urls[LinkedIn]"] == "https://linkedin.com/in/janedoe"
    assert res.payload["consent[data-retention]"] == "true"
    assert res.payload["cards[card_auth][fld_1]"] == "yes"


def test_lever_map_payload_unmapped_required(sample_user: User, sample_lever_posting: JobPosting):
    submitter = LeverSubmitter()
    questions = [
        ScreeningQuestion(
            id="c_custom",
            label="What is your deep learning thesis topic?",
            question_type=QuestionType.LONG_TEXT,
            required=True,
            raw_field_name="cards[custom_card][thesis]",
        )
    ]
    res = submitter.map_and_validate_payload(sample_user, sample_lever_posting, questions)
    assert res.status == "needs_review"
    assert len(res.unmapped_questions) == 1


def test_lever_submit_success(sample_user: User, sample_lever_posting: JobPosting):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v0/postings/netflix/4b0e8e4a-1111-2222-3333-444455556666"
        assert request.method == "POST"
        body = request.read().decode("latin1")
        assert 'name="resume"' in body
        assert 'name="name"' in body
        assert "Jane Doe" in body
        return httpx.Response(
            200, json={"ok": True, "applicationId": "lever-app-777", "redirect": "https://netflix.com/thanks"}
        )

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            submitter = LeverSubmitter(client=http)
            payload = {"name": "Jane Doe", "email": "jane@example.com"}
            stream = io.BytesIO(b"%PDF-mock-lever-bytes")
            return await submitter.submit(sample_user, sample_lever_posting, payload, stream, "Jane_Resume.pdf")

    resp = asyncio.run(run())
    assert resp.status == "submitted"
    assert resp.external_application_id == "lever-app-777"
    assert resp.redirect_url == "https://netflix.com/thanks"


def test_lever_submit_captcha_fallback(sample_user: User, sample_lever_posting: JobPosting):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "error": "reCAPTCHA verification failed"})

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            submitter = LeverSubmitter(client=http)
            stream = io.BytesIO(b"%PDF-mock")
            return await submitter.submit(sample_user, sample_lever_posting, {}, stream, "resume.pdf")

    resp = asyncio.run(run())
    assert resp.status == "manual_apply"
    assert resp.reason == "captcha_blocked"


def test_lever_submit_404_closed(sample_user: User, sample_lever_posting: JobPosting):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"ok": False, "error": "Posting not found"})

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            submitter = LeverSubmitter(client=http)
            stream = io.BytesIO(b"%PDF-mock")
            return await submitter.submit(sample_user, sample_lever_posting, {}, stream, "resume.pdf")

    resp = asyncio.run(run())
    assert resp.status == "stale_closed"
    assert resp.reason == "posting_closed"
