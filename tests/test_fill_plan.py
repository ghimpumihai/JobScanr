"""Fill plans for the remote-browser apply spike (#129). No network, no database."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from jobs import scrape_and_notify
from jobs.apply import fill_plan
from jobs.apply.base import QuestionOption, QuestionType, ScreeningQuestion

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

    conn, cur = _mock_conn([(55, 7, "123", POSTING["url"], "Engineer", "acme")])
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
    assert rows == [{"application_id": 55, "user_id": 7, "posting": POSTING}]


def test_upsert_fill_plan_replaces_the_previous_plan():
    from db import queries

    conn, cur = _mock_conn()
    with patch("db.queries.get_connection") as get_conn:
        get_conn.return_value.__enter__.return_value = conn
        queries.upsert_fill_plan(55, {"version": 1})
    sql, params = cur.execute.call_args[0]
    assert "ON CONFLICT (application_id) DO UPDATE SET plan = EXCLUDED.plan, built_at = NOW()" in sql
    assert params == (55, '{"version": 1}')
