"""Fill plans for the remote-browser apply spike (#129). No network, no database."""

import io
import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from jobs import scrape_and_notify
from jobs.apply import fill_plan
from jobs.apply.base import QuestionOption, QuestionType, ScreeningQuestion


@pytest.fixture(autouse=True)
def _no_answer_memory_db(monkeypatch):
    """build_fill_plans reads and writes the answer memory; no test here may reach a real database."""
    from db import queries

    monkeypatch.setattr(queries, "get_user_answers", lambda user_ids: {uid: [] for uid in user_ids})
    monkeypatch.setattr(queries, "add_pending_questions", lambda user_id, questions: [])


USER = {
    "id": 7,
    "auth_user_id": "u",
    "email": "jane@example.com",
    "resume_data": {"urls": {"linkedin": "https://linkedin.com/in/jane"}},
    "profile_filters": {},
    "screening_defaults": {"work_authorization": True, "requires_sponsorship": False},
}
POSTING = {
    "external_id": "123",
    "ats_identifier": "acme",
    "url": "https://job-boards.greenhouse.io/acme/jobs/123",
    "title": "Engineer",
    "ats_platform": "greenhouse",
}


def q(qid, label, qtype=QuestionType.SHORT_TEXT, required=True, options=None, name=None):
    return ScreeningQuestion(
        id=qid,
        label=label,
        question_type=qtype,
        required=required,
        options=options or [],
        raw_field_name=name or f"question_{qid}",
    )


def test_build_plan_splits_confident_answers_from_questions_for_the_user():
    yes_no = [QuestionOption(id=1, label="Yes"), QuestionOption(id=0, label="No")]
    questions = [
        q(0, "First Name", name="first_name"),
        q(1, "Are you legally authorized to work in the country?", QuestionType.SINGLE_SELECT, options=yes_no),
        q(2, "Will you require visa sponsorship?"),
        q(3, "LinkedIn Profile"),
        q(4, "Why do you want to work here?", QuestionType.LONG_TEXT, required=False),
        q(5, "What is your favourite colour?"),
        q(6, "Optional nickname", required=False),
        q(7, "Portfolio sample", QuestionType.FILE),
        q(8, "recaptcha", name="g-recaptcha-response"),
    ]
    plan = fill_plan.build_plan(questions, USER, POSTING["url"])

    assert plan["version"] == 1 and plan["platform"] == "greenhouse" and plan["posting_url"] == POSTING["url"]
    by_name = {f["name"]: f for f in plan["fields"]}
    assert set(by_name) == {"question_1", "question_2", "question_3"}  # standard fields and captcha skipped
    assert by_name["question_1"]["value"] == 1 and by_name["question_1"]["option_label"] == "Yes"
    assert by_name["question_2"]["value"] == "No"
    assert by_name["question_3"]["value"] == "https://linkedin.com/in/jane"
    # Open-ended (even optional), unanswered required and required files are left for the user; optional
    # unanswered ones are simply left blank.
    assert {(i["name"], i["reason"]) for i in plan["for_user"]} == {
        ("question_4", "open_ended"),
        ("question_5", "no_confident_answer"),
        ("question_7", "file"),
    }
    assert next(i for i in plan["for_user"] if i["name"] == "question_4")["type"] == "long_text"  # for drafting (#59)


def test_build_plan_classifies_long_labels_by_question_type():
    """#137: only free text counts as open-ended; long selects and checkboxes are fact questions."""
    yes_no = [QuestionOption(id=1, label="Yes"), QuestionOption(id=0, label="No")]
    sponsorship = (
        "Do you now or will you in the future need sponsorship for employment visa status in the country "
        "in which you are applying?"
    )
    sanctions = "Please confirm whether any of the below applies to you. Select all that apply. " * 2
    essay = (
        "Tell us about a time you disagreed with a colleague and how you resolved it, in as much detail as you like."
    )
    plan = fill_plan.build_plan(
        [
            q(1, sponsorship, QuestionType.SINGLE_SELECT, options=yes_no),
            q(2, sanctions, QuestionType.MULTI_SELECT, options=[QuestionOption(id=9, label="Citizen of Cuba")]),
            q(3, essay),
        ],
        USER,
        POSTING["url"],
    )
    assert all(len(x) > 100 for x in (sponsorship, sanctions, essay))
    assert plan["fields"] == [
        {"name": "question_1", "label": sponsorship, "type": "single_select", "value": 0, "option_label": "No"}
    ]
    assert [(i["name"], i["reason"]) for i in plan["for_user"]] == [
        ("question_2", "no_confident_answer"),  # reaches answer memory now
        ("question_3", "open_ended"),
    ]


def test_allowlist_parsing():
    assert fill_plan.allowlisted_user_ids("") == set()
    assert fill_plan.allowlisted_user_ids(" 3, 7,,x") == {3, 7}


def _client(status=200, questions=None, calls=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        return httpx.Response(status, json={"questions": questions or []})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.anyio
async def test_build_fill_plans_writes_one_plan_per_open_posting(monkeypatch):
    monkeypatch.setenv("REMOTE_APPLY_USER_IDS", "7")
    calls: list[str] = []
    questions = [{"id": 2, "label": "Will you require visa sponsorship?", "required": True, "fields": []}]
    cand = {"application_id": 55, "user_id": 7, "posting": POSTING}
    with (
        patch("db.queries.list_fill_plan_candidates", return_value=[cand]) as mock_list,
        patch("db.queries.upsert_fill_plan") as mock_upsert,
    ):
        async with _client(questions=questions, calls=calls) as client:
            assert await fill_plan.build_fill_plans([USER, {**USER, "id": 8}], client) == 1

    mock_list.assert_called_once_with([7])  # only allowlisted users
    assert calls == ["https://boards-api.greenhouse.io/v1/boards/acme/jobs/123?questions=true"]
    app_id, plan = mock_upsert.call_args[0]
    assert app_id == 55 and plan["fields"][0]["value"] == "No"
    # The bare form, not the board page (some boards redirect to the employer's site, Task 3.4).
    assert plan["posting_url"] == "https://job-boards.greenhouse.io/embed/job_app?for=acme&token=123"


@pytest.mark.anyio
@pytest.mark.parametrize("status", [404, 500])
async def test_build_fill_plans_skips_closed_or_failing_postings(monkeypatch, status):
    monkeypatch.setenv("REMOTE_APPLY_USER_IDS", "7")
    cand = {"application_id": 55, "user_id": 7, "posting": POSTING}
    with (
        patch("db.queries.list_fill_plan_candidates", return_value=[cand]),
        patch("db.queries.upsert_fill_plan") as mock_upsert,
    ):
        async with _client(status=status) as client:
            assert await fill_plan.build_fill_plans([USER], client) == 0
    mock_upsert.assert_not_called()


@pytest.mark.anyio
async def test_build_fill_plans_with_no_allowlist_touches_nothing(monkeypatch):
    monkeypatch.delenv("REMOTE_APPLY_USER_IDS", raising=False)
    calls: list[str] = []
    with patch("db.queries.list_fill_plan_candidates") as mock_list:
        async with _client(calls=calls) as client:
            assert await fill_plan.build_fill_plans([USER], client) == 0
    mock_list.assert_not_called()
    assert calls == []


def _pipeline_patches(users, jobs):
    return (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch("db.queries.get_all_companies", return_value=[{"id": 1, "name": "Co"}]),
        patch("jobs.scrape_and_notify.scrape_all", new_callable=AsyncMock, return_value=(jobs, [])),
        patch("db.queries.get_workday_board_states", return_value={}),
        patch("db.queries.get_workday_pod_backoff", return_value={}),
        patch("db.queries.save_workday_board_states"),
        patch("db.queries.save_workday_pod_backoff"),
        patch("db.queries.get_active_users", return_value=users),
        patch("db.queries.upsert_jobs", return_value=[]),
        patch("db.queries.delete_stale_jobs", return_value=0),
        patch("db.queries.close_unlisted_applications", return_value=0),
        patch("db.queries.upsert_user_matches"),
        patch("db.queries.stage_user_applications"),
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("allowlist", "dry_run", "builds"),
    [("", False, False), ("7", True, False), ("7", False, True)],
)
async def test_pipeline_builds_fill_plans_only_with_an_allowlist_and_never_on_dry_run(
    monkeypatch, allowlist, dry_run, builds
):
    monkeypatch.setenv("REMOTE_APPLY_USER_IDS", allowlist)
    args = MagicMock(profile=None, dry_run=dry_run, failures_file=None, platforms=None, skip_platforms=None)
    args.no_email = True
    users = [{**USER, "auto_apply_mode": "approval_required", "profile_filters": {"titles": ["engineer"]}}]
    patches = _pipeline_patches(users, [])
    for p in patches:
        p.start()
    try:
        with patch("jobs.apply.fill_plan.build_fill_plans", new_callable=AsyncMock, return_value=0) as mock_build:
            assert await scrape_and_notify.run_pipeline(args) == 0
    finally:
        for p in patches:
            p.stop()
    assert mock_build.called is builds


@pytest.mark.anyio
async def test_pipeline_continues_when_fill_plans_fail(monkeypatch):
    monkeypatch.setenv("REMOTE_APPLY_USER_IDS", "7")
    args = MagicMock(profile=None, dry_run=False, failures_file=None, platforms=None, skip_platforms=None)
    args.no_email = True
    users = [{**USER, "auto_apply_mode": "approval_required", "profile_filters": {"titles": ["engineer"]}}]
    patches = _pipeline_patches(users, [])
    for p in patches:
        p.start()
    try:
        with patch("jobs.apply.fill_plan.build_fill_plans", new_callable=AsyncMock, side_effect=RuntimeError("x")):
            assert await scrape_and_notify.run_pipeline(args) == 0
    finally:
        for p in patches:
            p.stop()


def _mock_conn(rows=None):
    conn, cur = MagicMock(), MagicMock()
    cur.fetchall.return_value = rows or []
    conn.cursor.return_value.__enter__.return_value = cur
    return conn, cur


def test_list_fill_plan_candidates_selects_stale_or_missing_greenhouse_to_apply_rows():
    from db import queries

    stored = {"version": 1, "for_user": []}
    conn, cur = _mock_conn(
        [
            (55, 7, "123", POSTING["url"], "Engineer", "acme", None),
            (56, 7, "123", POSTING["url"], "Engineer", "acme", stored),
        ]
    )
    with patch("db.queries.get_connection") as get_conn:
        get_conn.return_value.__enter__.return_value = conn
        assert queries.list_fill_plan_candidates([]) == []  # no query without users
        rows = queries.list_fill_plan_candidates([7])
    sql, params = cur.execute.call_args[0]
    assert "a.status = 'manual_apply'" in sql and "c.ats_platform = 'greenhouse'" in sql
    assert "p.built_at < NOW() - INTERVAL '1 day'" in sql
    # Rows with no plan first, then the stalest: the same 200 oldest rows must not take the limit every day.
    assert "ORDER BY p.built_at NULLS FIRST, a.id" in sql
    assert params == ([7], 200)
    assert "p.plan" in sql
    assert rows == [
        {"application_id": 55, "user_id": 7, "posting": POSTING, "previous_plan": None},
        {"application_id": 56, "user_id": 7, "posting": POSTING, "previous_plan": stored},
    ]


def test_upsert_fill_plan_replaces_the_previous_plan():
    from db import queries

    conn, cur = _mock_conn()
    with patch("db.queries.get_connection") as get_conn:
        get_conn.return_value.__enter__.return_value = conn
        queries.upsert_fill_plan(55, {"version": 1})
    sql, params = cur.execute.call_args[0]
    assert "ON CONFLICT (application_id) DO UPDATE SET plan = EXCLUDED.plan, built_at = NOW()" in sql
    assert params == (55, '{"version": 1}')


# --- LLM drafts of open-ended answers (#59) ------------------------------------------------------------------------

CV = "Backend engineer at Acme Ltd building Python services. " * 5
LONG_LABEL = "Please tell us, in your own words, " + "about a time you had to learn something new quickly " * 2
DRAFT_USER = {**USER, "llm_drafts_enabled": True, "resume_storage_path": "u/cv.pdf"}


def _groq(responses=None, requests=None):
    """Groq mock: answers each request with the next response, or a draft naming the question."""

    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        if responses:
            return responses.pop(0)
        question = json.loads(request.content)["messages"][1]["content"].split("<question>\n")[1].split("\n")[0]
        return httpx.Response(200, json={"choices": [{"message": {"content": f"Draft for {question}."}}]})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _entries():
    return [
        {"name": "question_4", "label": "Why Acme?", "reason": "open_ended", "type": "long_text"},
        {"name": "question_5", "label": LONG_LABEL, "reason": "open_ended", "type": "short_text"},
        {"name": "question_6", "label": LONG_LABEL + "?", "reason": "open_ended", "type": "single_select"},
        {"name": "question_7", "label": "Salary?", "reason": "no_confident_answer"},
        {"name": "question_8", "label": "Portfolio", "reason": "file"},
    ]


@pytest.mark.anyio
async def test_only_open_ended_free_text_questions_are_drafted():
    requests: list[httpx.Request] = []
    plan = {"for_user": _entries()}
    with patch("jobs.apply.fill_plan._load_cv_text", return_value=CV):
        async with _groq(requests=requests) as client:
            await fill_plan.add_drafts(plan, None, DRAFT_USER, "Build payments.", fill_plan.Drafter(client, "k", "m"))
    assert len(requests) == 2
    q4, q5, q6, q7, q8 = plan["for_user"]
    assert q4["draft"] == "Draft for Why Acme?." and q4["draft_status"] == "generated"
    assert q5["draft_status"] == "generated"
    assert all("draft_status" not in e for e in (q6, q7, q8))
    body = json.loads(requests[0].content)
    assert body["model"] == "m" and "Build payments." in body["messages"][1]["content"]


@pytest.mark.anyio
async def test_a_refresh_keeps_generated_drafts_and_retries_unanswered_ones():
    previous = {
        "for_user": [
            {
                "name": "question_4",
                "label": "Why Acme?",
                "draft": "My edited-by-nobody draft.",
                "draft_status": "generated",
            },
            {"name": "question_5", "label": LONG_LABEL, "draft_status": "unanswered", "draft_reason": "llm_error"},
        ]
    }
    requests: list[httpx.Request] = []
    plan = {"for_user": _entries()}
    with patch("jobs.apply.fill_plan._load_cv_text", return_value=CV):
        async with _groq(requests=requests) as client:
            await fill_plan.add_drafts(plan, previous, DRAFT_USER, "JD", fill_plan.Drafter(client, "k"))
    assert len(requests) == 1  # only question_5
    assert plan["for_user"][0]["draft"] == "My edited-by-nobody draft."
    assert plan["for_user"][1]["draft_status"] == "generated" and "draft_reason" not in plan["for_user"][1]


@pytest.mark.anyio
async def test_a_changed_question_label_is_drafted_again():
    previous = {"for_user": [{"name": "question_4", "label": "Why us?", "draft": "Old.", "draft_status": "generated"}]}
    plan = {"for_user": _entries()[:1]}
    with patch("jobs.apply.fill_plan._load_cv_text", return_value=CV):
        async with _groq() as client:
            await fill_plan.add_drafts(plan, previous, DRAFT_USER, "JD", fill_plan.Drafter(client, "k"))
    assert plan["for_user"][0]["draft"] == "Draft for Why Acme?."


@pytest.mark.anyio
async def test_an_exhausted_question_trips_the_breaker_for_the_rest_of_the_run():
    requests: list[httpx.Request] = []
    first, second = {"for_user": _entries()}, {"for_user": _entries()}
    with (
        patch("jobs.apply.fill_plan._load_cv_text", return_value=CV),
        patch("jobs.apply.llm_answers.asyncio.sleep", new_callable=AsyncMock),
    ):
        async with _groq(responses=[httpx.Response(429)] * 3, requests=requests) as client:
            drafter = fill_plan.Drafter(client, "k")
            await fill_plan.add_drafts(first, None, DRAFT_USER, "JD", drafter)
            await fill_plan.add_drafts(second, None, DRAFT_USER, "JD", drafter)
    assert len(requests) == 3 and drafter.tripped
    assert first["for_user"][0]["draft_status"] == "unanswered"
    assert first["for_user"][0]["draft_reason"] == "rate_limit_exceeded"
    assert "draft_status" not in first["for_user"][1]  # tried again on the next run
    assert all("draft_status" not in e for e in second["for_user"])


@pytest.mark.anyio
async def test_no_cv_text_means_no_drafts_and_no_groq_calls():
    requests: list[httpx.Request] = []
    plan = {"for_user": _entries()}
    with patch("jobs.apply.fill_plan._load_cv_text", return_value=None) as load:
        async with _groq(requests=requests) as client:
            drafter = fill_plan.Drafter(client, "k")
            await fill_plan.add_drafts(plan, None, DRAFT_USER, "JD", drafter)
            await fill_plan.add_drafts({"for_user": _entries()}, None, DRAFT_USER, "JD", drafter)
    assert requests == [] and load.call_count == 1  # cached per user, even when there is no text
    assert all("draft_status" not in e for e in plan["for_user"])


def test_load_cv_text_reads_validates_and_extracts_in_memory():
    pdf = b"%PDF-1.4 fake"
    with (
        patch(
            "jobs.apply.fill_plan.download_resume_stream", return_value=(io.BytesIO(pdf), "x.pdf", "application/pdf")
        ) as dl,
        patch("jobs.apply.llm_answers.extract_cv_text", return_value=CV) as extract,
    ):
        assert fill_plan._load_cv_text(DRAFT_USER) == CV
    dl.assert_called_once_with("u/cv.pdf", owner_id="u")
    extract.assert_called_once_with(pdf, "x.pdf")


@pytest.mark.parametrize(
    ("user", "download"),
    [
        ({**DRAFT_USER, "resume_storage_path": None}, None),
        (DRAFT_USER, httpx.ConnectError("down")),
        (DRAFT_USER, (io.BytesIO(b"MZ not a pdf"), "x.pdf", "application/pdf")),  # refused by validate_cv
        (DRAFT_USER, (io.BytesIO(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"x" * 300), "x.doc", "application/msword")),
    ],
)
def test_load_cv_text_gives_none_for_unusable_cvs(caplog, user, download):
    kwargs = {"side_effect": download} if isinstance(download, Exception) else {"return_value": download}
    caplog.set_level(logging.WARNING)
    with patch("jobs.apply.fill_plan.download_resume_stream", **kwargs):
        assert fill_plan._load_cv_text(user) is None
    assert ("Drafts:" in caplog.text) is bool(user.get("resume_storage_path"))  # the reason is logged (FR2.2)


GH_JOB = {
    "content": "&lt;p&gt;Build &lt;b&gt;payments&lt;/b&gt;.&lt;/p&gt;",
    "questions": [
        {"id": 4, "label": "Why Acme?", "required": False, "fields": [{"name": "question_4", "type": "textarea"}]}
    ],
}


def _pipeline_client(groq_requests):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.groq.com":
            groq_requests.append(request)
            return httpx.Response(200, json={"choices": [{"message": {"content": "I build payments at Acme."}}]})
        return httpx.Response(200, json=GH_JOB)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _build(user, cands, groq_requests, load=CV):
    with (
        patch("db.queries.list_fill_plan_candidates", return_value=cands),
        patch("db.queries.upsert_fill_plan") as upsert,
        patch("jobs.apply.fill_plan._load_cv_text", return_value=load) as load_cv,
    ):
        async with _pipeline_client(groq_requests) as client:
            await fill_plan.build_fill_plans([user], client)
    return [c.args[1] for c in upsert.call_args_list], load_cv


@pytest.mark.anyio
async def test_build_fill_plans_drafts_from_the_plain_text_description(monkeypatch):
    monkeypatch.setenv("REMOTE_APPLY_USER_IDS", "7")
    monkeypatch.setenv("GROQ_API_KEY", "gsk")
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    groq: list[httpx.Request] = []
    cands = [{"application_id": 55, "user_id": 7, "posting": POSTING, "previous_plan": None}]
    plans, _ = await _build(DRAFT_USER, cands, groq)
    assert plans[0]["for_user"][0]["draft"] == "I build payments at Acme."
    body = json.loads(groq[0].content)
    assert body["model"] == "openai/gpt-oss-120b"
    assert "<job_description>\nBuild payments .\n</job_description>" in body["messages"][1]["content"]
    assert groq[0].headers["authorization"] == "Bearer gsk"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("user", "key"),
    [
        ({**DRAFT_USER, "llm_drafts_enabled": False}, "gsk"),
        ({**DRAFT_USER, "resume_storage_path": None}, "gsk"),
        (DRAFT_USER, ""),
    ],
)
async def test_build_fill_plans_without_opt_in_cv_or_key_sends_nothing_to_groq(monkeypatch, caplog, user, key):
    monkeypatch.setenv("REMOTE_APPLY_USER_IDS", "7")
    monkeypatch.setenv("GROQ_API_KEY", key)
    caplog.set_level(logging.WARNING)
    groq: list[httpx.Request] = []
    cands = [{"application_id": n, "user_id": 7, "posting": POSTING, "previous_plan": None} for n in (55, 56)]
    plans, load_cv = await _build(user, cands, groq)
    assert groq == [] and load_cv.call_count == 0 and len(plans) == 2
    assert all("draft_status" not in e for plan in plans for e in plan["for_user"])
    assert caplog.text.count("GROQ_API_KEY is not set") == (1 if not key else 0)  # logged once per run


@pytest.mark.anyio
async def test_build_fill_plans_reads_the_cv_once_per_user(monkeypatch):
    monkeypatch.setenv("REMOTE_APPLY_USER_IDS", "7")
    monkeypatch.setenv("GROQ_API_KEY", "gsk")
    groq: list[httpx.Request] = []
    cands = [{"application_id": n, "user_id": 7, "posting": POSTING, "previous_plan": None} for n in (55, 56)]
    plans, load_cv = await _build(DRAFT_USER, cands, groq)
    assert load_cv.call_count == 1 and len(groq) == 2
    assert all(plan["for_user"][0]["draft_status"] == "generated" for plan in plans)


@pytest.mark.anyio
async def test_a_drafting_error_still_writes_the_plan(monkeypatch):
    monkeypatch.setenv("REMOTE_APPLY_USER_IDS", "7")
    monkeypatch.setenv("GROQ_API_KEY", "gsk")
    cands = [{"application_id": 55, "user_id": 7, "posting": POSTING, "previous_plan": None}]
    with patch("jobs.apply.fill_plan.add_drafts", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
        plans, _ = await _build(DRAFT_USER, cands, [])
    assert len(plans) == 1 and plans[0]["for_user"][0]["name"] == "question_4"


# --- Answer memory: SKIP and links (answer-memory Phase 3) -------------------------------------------------------


def _reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


@pytest.mark.anyio
async def test_a_skipped_question_joins_the_memory_without_tripping_the_breaker():
    requests: list[httpx.Request] = []
    plan = {"for_user": _entries()}
    with patch("jobs.apply.fill_plan._load_cv_text", return_value=CV):
        async with _groq(responses=[_reply("SKIP")], requests=requests) as client:
            drafter = fill_plan.Drafter(client, "k")
            await fill_plan.add_drafts(plan, None, DRAFT_USER, "JD", drafter)
    q4, q5 = plan["for_user"][:2]
    assert q4["reason"] == "no_confident_answer" and not any(k.startswith("draft") for k in q4)
    assert not drafter.tripped and q5["draft_status"] == "generated" and len(requests) == 2


@pytest.mark.anyio
async def test_a_question_skipped_before_is_not_sent_again():
    previous = {"for_user": [{"name": "question_4", "label": "Why Acme?", "reason": "no_confident_answer"}]}
    requests: list[httpx.Request] = []
    plan = {"for_user": _entries()[:1]}
    with patch("jobs.apply.fill_plan._load_cv_text", return_value=CV):
        async with _groq(requests=requests) as client:
            await fill_plan.add_drafts(plan, previous, DRAFT_USER, "JD", fill_plan.Drafter(client, "k"))
    assert requests == [] and plan["for_user"][0]["reason"] == "no_confident_answer"


SALARY = {
    "id": 1,
    "question": "What are your salary expectations?",
    "question_key": "what are your salary expectations",
}


def _personal(label, name="question_7"):
    return {"name": name, "label": label, "reason": "no_confident_answer"}


async def _link(entries, saved, responses=None, use_groq=True, previous=None, drafter=None):
    requests: list[httpx.Request] = []
    plan = {"for_user": entries}
    with patch("jobs.apply.llm_answers.asyncio.sleep", new_callable=AsyncMock):
        async with _groq(responses=list(responses or []), requests=requests) as client:
            drafter = drafter or fill_plan.Drafter(client, "k")
            drafter.client = client
            new = await fill_plan.add_memory_links(plan, previous, saved, drafter, use_groq, 7)
    return plan["for_user"], new, requests, drafter


@pytest.mark.anyio
async def test_the_same_question_text_links_exactly_without_groq():
    entries, new, requests, _ = await _link([_personal("  What are your SALARY expectations?* ")], [SALARY])
    assert entries[0]["memory_id"] == 1 and entries[0]["memory_match"] == "exact"
    assert new == [] and requests == []


@pytest.mark.anyio
async def test_a_rephrased_question_links_as_similar_and_groq_sees_only_question_texts():
    entries, new, requests, _ = await _link([_personal("Expected salary (EUR)?")], [SALARY], [_reply("1")])
    assert entries[0]["memory_id"] == 1 and entries[0]["memory_match"] == "similar" and new == []
    user_message = json.loads(requests[0].content)["messages"][1]["content"]
    assert "1. What are your salary expectations?" in user_message and "Expected salary (EUR)?" in user_message


@pytest.mark.anyio
async def test_unmatched_questions_are_returned_once_as_pending():
    entries = [_personal("When can you start?"), _personal("When can you start?", "question_8")]
    entries, new, requests, drafter = await _link(entries, [SALARY], [_reply("NONE")])
    assert new == [{"question": "When can you start?", "question_key": "when can you start"}]
    assert len(requests) == 1 and "memory_id" not in entries[0] and not drafter.tripped


@pytest.mark.anyio
async def test_a_groq_failure_trips_the_breaker_and_still_saves_the_question():
    entries = [_personal("When can you start?"), _personal("Notice period?", "question_8")]
    entries, new, requests, drafter = await _link(entries, [SALARY], [httpx.Response(401)])
    assert drafter.tripped and len(requests) == 1  # the second question is not sent
    assert [n["question_key"] for n in new] == ["when can you start", "notice period"]


@pytest.mark.anyio
async def test_without_groq_only_exact_matching_runs():
    entries = [_personal("What are your salary expectations?"), _personal("Expected salary?", "question_8")]
    entries, new, requests, _ = await _link(entries, [SALARY], use_groq=False)
    assert requests == [] and entries[0]["memory_match"] == "exact"
    assert new == [{"question": "Expected salary?", "question_key": "expected salary"}]


@pytest.mark.anyio
async def test_an_empty_memory_needs_no_groq_call():
    _, new, requests, _ = await _link([_personal("When can you start?")], [])
    assert requests == [] and len(new) == 1


@pytest.mark.anyio
async def test_previous_links_are_kept_while_their_saved_row_exists():
    previous = {"for_user": [{**_personal("Expected salary?"), "memory_id": 1, "memory_match": "similar"}]}
    entries, new, requests, _ = await _link([_personal("Expected salary?")], [SALARY], previous=previous)
    assert (entries[0]["memory_id"], entries[0]["memory_match"], requests, new) == (1, "similar", [], [])
    gone = {"for_user": [{**_personal("Expected salary?"), "memory_id": 99, "memory_match": "similar"}]}
    entries, new, requests, _ = await _link([_personal("Expected salary?")], [SALARY], [_reply("NONE")], previous=gone)
    assert "memory_id" not in entries[0] and len(requests) == 1 and len(new) == 1


@pytest.mark.anyio
async def test_only_personal_fact_entries_are_linked():
    entries = [
        {
            "name": "question_4",
            "label": "What are your salary expectations?",
            "reason": "open_ended",
            "type": "long_text",
        },
        {"name": "question_8", "label": "What are your salary expectations?", "reason": "file"},
    ]
    entries, new, requests, _ = await _link(entries, [SALARY])
    assert all("memory_id" not in e for e in entries) and new == [] and requests == []


@pytest.mark.anyio
async def test_a_full_memory_saves_nothing_more_and_says_so_once(caplog):
    caplog.set_level(logging.WARNING)
    saved = [{"id": i, "question": f"Q{i}", "question_key": f"q{i}"} for i in range(fill_plan.MEMORY_CAP)]
    _, new, _, drafter = await _link([_personal("When can you start?")], saved, use_groq=False)
    _, new2, _, _ = await _link([_personal("Notice period?")], saved, use_groq=False, drafter=drafter)
    assert new == new2 == [] and caplog.text.count("is full") == 1


MEMORY_JOB = {
    "content": "<p>Build payments.</p>",
    "questions": [
        {
            "id": 7,
            "label": "What are your salary expectations?",
            "required": True,
            "fields": [{"name": "question_7", "type": "input_text"}],
        },
        {
            "id": 8,
            "label": "When can you start?",
            "required": True,
            "fields": [{"name": "question_8", "type": "input_text"}],
        },
    ],
}


async def _build_memory(user, cands, saved, groq_requests, add_pending=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.groq.com":
            groq_requests.append(request)
            return _reply("NONE")
        return httpx.Response(200, json=MEMORY_JOB)

    added: list[list[dict]] = []

    def fake_add(user_id, questions):
        added.append(questions)
        return [{"id": 100 + i, **q} for i, q in enumerate(questions)]

    with (
        patch("db.queries.list_fill_plan_candidates", return_value=cands),
        patch("db.queries.upsert_fill_plan") as upsert,
        patch("db.queries.get_user_answers", return_value={7: list(saved)}),
        patch("db.queries.add_pending_questions", side_effect=add_pending or fake_add),
        patch("jobs.apply.fill_plan._load_cv_text", return_value=CV),
    ):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await fill_plan.build_fill_plans([user], client)
    return [c.args[1] for c in upsert.call_args_list], added


@pytest.mark.anyio
async def test_build_fill_plans_links_known_questions_and_saves_new_ones_once(monkeypatch):
    monkeypatch.setenv("REMOTE_APPLY_USER_IDS", "7")
    monkeypatch.setenv("GROQ_API_KEY", "gsk")
    groq: list[httpx.Request] = []
    cands = [{"application_id": n, "user_id": 7, "posting": POSTING, "previous_plan": None} for n in (55, 56)]
    plans, added = await _build_memory(DRAFT_USER, cands, [SALARY], groq)
    for plan in plans:
        salary, start = plan["for_user"]
        assert (salary["memory_id"], salary["memory_match"]) == (1, "exact")
    assert "memory_id" not in plans[0]["for_user"][1]  # new: saved as pending
    assert plans[1]["for_user"][1]["memory_id"] == 100  # the second posting links to the row the first one added
    assert added == [[{"question": "When can you start?", "question_key": "when can you start"}], []]
    assert len(groq) == 1  # one match attempt, for the new question only


@pytest.mark.anyio
@pytest.mark.parametrize(("opted_in", "key"), [(False, "gsk"), (True, "")])
async def test_build_fill_plans_without_opt_in_or_key_matches_exactly_and_never_calls_groq(monkeypatch, opted_in, key):
    monkeypatch.setenv("REMOTE_APPLY_USER_IDS", "7")
    monkeypatch.setenv("GROQ_API_KEY", key)
    groq: list[httpx.Request] = []
    cands = [{"application_id": 55, "user_id": 7, "posting": POSTING, "previous_plan": None}]
    plans, added = await _build_memory({**DRAFT_USER, "llm_drafts_enabled": opted_in}, cands, [SALARY], groq)
    assert groq == [] and plans[0]["for_user"][0]["memory_match"] == "exact" and len(added[0]) == 1


@pytest.mark.anyio
async def test_plans_are_written_when_the_answer_memory_fails(monkeypatch, caplog):
    monkeypatch.setenv("REMOTE_APPLY_USER_IDS", "7")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    caplog.set_level(logging.WARNING)
    cands = [{"application_id": 55, "user_id": 7, "posting": POSTING, "previous_plan": None}]
    plans, _ = await _build_memory(USER, cands, [], [], add_pending=RuntimeError("db down"))
    assert len(plans) == 1 and "Answer memory for application 55 failed" in caplog.text
    with (
        patch("db.queries.list_fill_plan_candidates", return_value=cands),
        patch("db.queries.upsert_fill_plan") as upsert,
        patch("db.queries.get_user_answers", side_effect=RuntimeError("relation user_answers does not exist")),
    ):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=MEMORY_JOB))
        ) as c:
            assert await fill_plan.build_fill_plans([USER], c) == 1
    assert all("memory_id" not in e for e in upsert.call_args[0][1]["for_user"])
    assert "Answer memory unavailable this run" in caplog.text


def test_fill_plans_have_their_own_entry_point_for_their_own_workflow_step():
    users = [USER]
    with (
        patch("db.queries.get_active_users", return_value=users),
        patch("jobs.apply.fill_plan.build_fill_plans", new_callable=AsyncMock, return_value=3) as build,
    ):
        assert fill_plan.main() == 0
    build.assert_awaited_once_with(users)
    workflow = (Path(__file__).resolve().parent.parent / ".github" / "workflows" / "digest.yml").read_text()
    scrape, plans = (
        workflow.split("- name: Build remote fill plans")[0],
        workflow.split("- name: Build remote fill plans")[1],
    )
    plans = plans.split("- name:")[0]
    assert "python -m jobs.apply.fill_plan" in plans
    for key in ("SUPABASE_SERVICE_ROLE_KEY", "REMOTE_APPLY_USER_IDS"):
        assert key in plans and key not in scrape  # the scraping step never gets them


@pytest.mark.anyio
@pytest.mark.parametrize(("opted_in", "key"), [(False, "gsk"), (True, "")])
async def test_questions_skipped_before_keep_their_saved_answers_when_drafting_is_off(monkeypatch, opted_in, key):
    monkeypatch.setenv("REMOTE_APPLY_USER_IDS", "7")
    monkeypatch.setenv("GROQ_API_KEY", key)
    previous = {"for_user": [{"name": "question_4", "label": "Why Acme?", "reason": "no_confident_answer"}]}
    cands = [{"application_id": 55, "user_id": 7, "posting": POSTING, "previous_plan": previous}]
    groq: list[httpx.Request] = []
    with (
        patch("db.queries.list_fill_plan_candidates", return_value=cands),
        patch("db.queries.upsert_fill_plan") as upsert,
        patch(
            "db.queries.get_user_answers",
            return_value={7: [{"id": 5, "question": "Why Acme?", "question_key": "why acme"}]},
        ),
    ):
        async with _pipeline_client(groq) as client:
            await fill_plan.build_fill_plans([{**DRAFT_USER, "llm_drafts_enabled": opted_in}], client)
    entry = upsert.call_args[0][1]["for_user"][0]
    assert (entry["reason"], entry["memory_id"], entry["memory_match"]) == ("no_confident_answer", 5, "exact")
    assert groq == []


@pytest.mark.anyio
async def test_an_exact_match_replaces_a_similar_link_from_the_previous_plan():
    exact = {"id": 2, "question": "Expected salary?", "question_key": "expected salary"}
    previous = {"for_user": [{**_personal("Expected salary?"), "memory_id": 1, "memory_match": "similar"}]}
    entries, new, requests, _ = await _link([_personal("Expected salary?")], [SALARY, exact], previous=previous)
    assert (entries[0]["memory_id"], entries[0]["memory_match"], new, requests) == (2, "exact", [], [])
