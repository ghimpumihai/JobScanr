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


def test_build_personalized_html_digest_standard_and_high_volume():
    user = {"email": "alice@example.com"}

    # 1. Standard day: 3 roles (<= EMAIL_MAX_INLINE_JOBS)
    matches_standard = [
        {
            "title": "Junior Python Dev",
            "company_name": "PyCorp",
            "location": "London",
            "url": "https://pycorp.com/job/1",
            "compensation": "£45k",
            "ats_platform": "greenhouse",
        },
        {
            "title": "Backend Dev",
            "company_name": "Datadog",
            "location": "Paris",
            "url": "https://datadog.com/job/2",
            "compensation": "€60k",
            "ats_platform": "lever",
        },
    ]

    html_std = notify.build_personalized_html_digest(user, matches_standard)
    assert "alice@example.com" in html_std
    assert "2 new matching early-career roles" in html_std
    assert "PyCorp" in html_std
    assert "Datadog" in html_std
    assert "Apply &rarr;" in html_std
    assert "£45k" in html_std
    assert "via Greenhouse" in html_std
    # No bridge card on standard volume
    assert "more matching roles on your JobScanr portal" not in html_std

    # 2. High-volume day: 16 roles (> EMAIL_MAX_INLINE_JOBS = 4)
    companies = ["Revolut", "Spotify", "Datadog", "Cloudflare", "Amazon", "Monzo", "Wise", "Scale AI"]
    matches_high = [
        {
            "title": f"Software Engineer {i + 1}",
            "company_name": companies[i % len(companies)],
            "location": "London, UK",
            "url": f"https://example.com/job/{i + 1}",
            "compensation": "€60,000 / yr",
            "ats_platform": "greenhouse",
        }
        for i in range(16)
    ]

    html_hv = notify.build_personalized_html_digest(user, matches_high)
    assert "16 new matching early-career roles" in html_hv
    # Displays top 4 inline
    assert "Software Engineer 1" in html_hv
    assert "Software Engineer 4" in html_hv
    # Bridges the remaining 12 roles
    assert "+12 more matching roles on your JobScanr portal" in html_hv
    assert "View all 16 matches on JobScanr &rarr;" in html_hv
    assert "Amazon" in html_hv
    assert "Monzo" in html_hv

    # 3. Zero-match day: Heartbeat telemetry
    html_empty = notify.build_personalized_html_digest(user, [])
    assert "All systems healthy — 388 boards checked" in html_empty
    assert "● Radar Active" in html_empty
    assert "388 / 388" in html_empty
    assert "0 errors" in html_empty


def test_send_user_digest_empty():
    user = {"email": "bob@example.com"}
    res = notify.send_user_digest(user, [], send_heartbeat=False)
    assert res is None


def test_send_user_digest_heartbeat():
    user = {"email": "bob@example.com"}
    with patch("jobs.notify._send_email", return_value="MSG-HEARTBEAT") as mock_send:
        res = notify.send_user_digest(user, [], send_heartbeat=True)
        assert res == "MSG-HEARTBEAT"
        mock_send.assert_called_once()
        subject = mock_send.call_args[1]["subject"]
        assert "Radar Active" in subject


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
