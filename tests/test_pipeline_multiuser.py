from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db import queries
from jobs import enrich, notify, scrape_and_notify


@pytest.fixture(autouse=True)
def reset_pool():
    queries.close_pool()
    yield
    queries.close_pool()


# ---------------------------------------------------------------------------
# passes_prefilter_multiuser
# ---------------------------------------------------------------------------


def test_passes_prefilter_multiuser_union():
    user_a = {
        "id": 1,
        "profile_filters": {
            "titles": ["frontend engineer"],
            "levels": ["junior"],
            "locations": ["london"],
            "excluded_title_keywords": [],
        },
    }
    user_b = {
        "id": 2,
        "profile_filters": {
            "titles": ["backend engineer"],
            "levels": ["junior"],
            "locations": ["berlin"],
            "excluded_title_keywords": [],
        },
    }

    # Job for User A
    job_a = {"title": "Junior Frontend Engineer", "location": "London, UK"}
    assert enrich.passes_prefilter_multiuser(job_a, [user_a, user_b]) is True

    # Job for User B
    job_b = {"title": "Junior Backend Engineer", "location": "Berlin, Germany"}
    assert enrich.passes_prefilter_multiuser(job_b, [user_a, user_b]) is True

    # Job for neither
    job_c = {"title": "Senior DevOps Engineer", "location": "Paris, France"}
    assert enrich.passes_prefilter_multiuser(job_c, [user_a, user_b]) is False


def test_passes_prefilter_multiuser_empty_users():
    job = {"title": "Junior Software Engineer", "location": "Remote"}
    with patch("jobs.enrich.passes_prefilter", return_value=True) as mock_pf:
        assert enrich.passes_prefilter_multiuser(job, []) is True
        mock_pf.assert_called_once_with(job)


# ---------------------------------------------------------------------------
# db queries: stage_user_applications & notifications
# ---------------------------------------------------------------------------


def test_stage_user_applications_executes():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.rowcount = 2
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    items = [
        {"job_id": 101, "status": "pending_approval"},
        {"job_id": 102, "status": "manual_apply"},
    ]

    with patch("db.queries.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        written = queries.stage_user_applications(1, items)

        assert written == 2
        mock_cur.executemany.assert_called_once()
        sql, rows = mock_cur.executemany.call_args[0]
        assert "INSERT INTO applications" in sql
        assert rows == [(1, 101, "pending_approval"), (1, 102, "manual_apply")]


def test_get_user_unnotified_matches():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = [
        (
            501,
            "Junior Dev",
            "Acme Corp",
            "Remote",
            "https://acme.com/jobs/1",
            "€50k",
            "2026-11-01",
            "greenhouse",
            1.0,
        )
    ]
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch("db.queries.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        matches = queries.get_user_unnotified_matches(1)

        assert len(matches) == 1
        assert matches[0]["id"] == 501
        assert matches[0]["title"] == "Junior Dev"
        assert matches[0]["company_name"] == "Acme Corp"


def test_get_user_recent_application_activity():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    # 3 sequential execute calls: submitted, needs_review, manual_apply
    mock_cur.fetchall.side_effect = [
        [(1, "Role 1", "Corp A", {"confirmation_id": "CONF-123"}, "2026-10-11T10:00:00Z")],
        [(2, "Role 2", "Corp B", "https://corp-b.com/review")],
        [(3, "Role 3", "Corp C", "Berlin", "https://corp-c.com/apply", "€60k")],
    ]
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch("db.queries.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        act = queries.get_user_recent_application_activity(1)

        assert len(act["submitted_today"]) == 1
        assert act["submitted_today"][0]["confirmation"] == "CONF-123"
        assert len(act["needs_review"]) == 1
        assert len(act["manual_apply"]) == 1


def test_mark_user_matches_notified():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.rowcount = 3
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch("db.queries.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        res = queries.mark_user_matches_notified(1, [10, 20, 30])
        assert res == 3
        mock_cur.execute.assert_called_once()
        sql, params = mock_cur.execute.call_args[0]
        assert "UPDATE user_job_matches" in sql
        assert params == (1, [10, 20, 30])


# ---------------------------------------------------------------------------
# jobs.notify: personalized HTML digest & isolation
# ---------------------------------------------------------------------------


def test_build_personalized_html_digest_sections_and_isolation():
    user = {"email": "alice@example.com"}
    matches = [
        {
            "title": "Junior Python Dev",
            "company_name": "PyCorp",
            "location": "London",
            "url": "https://pycorp.com/job/1",
            "compensation": "£45k",
            "application_deadline": "2026-12-01",
        }
    ]
    activity = {
        "submitted_today": [{"title": "Software Eng", "company_name": "Alpha Inc", "confirmation": "ALPHA-99"}],
        "needs_review": [{"title": "Fullstack Eng", "company_name": "Beta Co", "url": "https://beta.com/form"}],
        "manual_apply": [
            {
                "title": "Backend Eng",
                "company_name": "Gamma Ltd",
                "location": "Remote",
                "compensation": "€60k",
                "url": "https://gamma.com/workday",
            }
        ],
    }

    html = notify.build_personalized_html_digest(user, matches, activity)

    assert "alice@example.com" in html
    # Section 1
    assert "Applications Submitted Today (1)" in html
    assert "ALPHA-99" in html
    # Section 2
    assert "Actions Required (1)" in html
    assert "Complete Review &rarr;" in html
    # Section 3
    assert "1-Click Manual Apply Roles (1)" in html
    assert "Gamma Ltd" in html
    # Section 4
    assert "Newly Discovered Matching Postings (1)" in html
    assert "PyCorp" in html


def test_send_user_digest_empty():
    user = {"email": "bob@example.com"}
    res = notify.send_user_digest(user, [], {"submitted_today": [], "needs_review": [], "manual_apply": []})
    assert res is None


# ---------------------------------------------------------------------------
# jobs.scrape_and_notify: pipeline staging logic
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_run_pipeline_multiuser_flow():
    mock_args = MagicMock()
    mock_args.profile = None
    mock_args.dry_run = False
    mock_args.failures_file = None

    users = [
        {
            "id": 1,
            "email": "user1@example.com",
            "profile_filters": {
                "titles": ["software engineer"],
                "levels": ["junior"],
                "locations": ["remote"],
            },
            "auto_apply_mode": "approval_required",
        },
        {
            "id": 2,
            "email": "user2@example.com",
            "profile_filters": {
                "titles": ["backend engineer"],
                "levels": ["junior"],
                "locations": ["remote"],
            },
            "auto_apply_mode": "auto_submit",
        },
    ]

    scraped_jobs = [
        {
            "external_id": "ext-1",
            "title": "Junior Software Engineer",
            "company_id": 10,
            "company_name": "Greenhouse Co",
            "location": "Remote",
            "ats_platform": "greenhouse",
            "description": "Python developer role",
            "url": "https://jobs.greenhouse.io/1",
        },
        {
            "external_id": "ext-2",
            "title": "Junior Backend Engineer",
            "company_id": 20,
            "company_name": "Workday Co",
            "location": "Remote",
            "ats_platform": "workday",
            "description": "Backend services",
            "url": "https://workday.com/2",
        },
    ]

    with (
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch("db.queries.get_all_companies", return_value=[{"id": 1, "name": "Co"}]),
        patch("jobs.scrape_and_notify.scrape_all", new_callable=AsyncMock) as mock_scrape,
        patch("db.queries.get_active_users", return_value=users),
        patch("db.queries.upsert_jobs") as mock_upsert,
        patch("db.queries.delete_stale_jobs", return_value=0),
        patch("db.queries.upsert_user_matches") as mock_upsert_matches,
        patch("db.queries.stage_user_applications") as mock_stage_apps,
        patch("jobs.notify.email_configured", return_value=True),
        patch("jobs.notify.send_user_digest", return_value="MSG-1"),
        patch("db.queries.mark_user_matches_notified") as mock_mark_notified,
        patch("db.queries.get_user_unnotified_matches", return_value=[{"id": 100}]),
        patch("db.queries.get_user_recent_application_activity", return_value={}),
    ):
        mock_scrape.return_value = (scraped_jobs, [])
        mock_upsert.return_value = [{"id": 100, "external_id": "ext-1", "company_id": 10}]

        # Set job IDs to simulate upsert return
        scraped_jobs[0]["id"] = 100
        scraped_jobs[1]["id"] = 200

        ret = await scrape_and_notify.run_pipeline(mock_args)
        assert ret == 0

        # Assert upsert user matches called for both users
        assert mock_upsert_matches.call_count == 2

        # Assert staging called
        # User 1 (approval_required, greenhouse) -> pending_approval
        # User 2 (auto_submit, workday) -> manual_apply
        assert mock_stage_apps.call_count == 2
        user1_stage_call = mock_stage_apps.call_args_list[0]
        assert user1_stage_call[0][0] == 1
        assert user1_stage_call[0][1][0]["status"] == "pending_approval"

        user2_stage_call = mock_stage_apps.call_args_list[1]
        assert user2_stage_call[0][0] == 2
        assert user2_stage_call[0][1][0]["status"] == "manual_apply"

        assert mock_mark_notified.call_count == 2
