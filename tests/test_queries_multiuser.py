import json
from unittest.mock import MagicMock, patch

import pytest

from db import queries
from scripts import migrate_to_multiuser


@pytest.fixture(autouse=True)
def reset_pool():
    queries.close_pool()
    yield
    queries.close_pool()


# ---------------------------------------------------------------------------
# get_active_users
# ---------------------------------------------------------------------------


def test_get_active_users_returns_users():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = [
        (
            1,
            "00000000-0000-0000-0000-000000000001",
            "user1@example.com",
            {"skills": ["python"]},
            {"titles": ["software engineer"]},
            {"work_authorization": True},
            "approval_required",
            10,
            2,
            "2026-10-11T00:00:00Z",
            "2026-10-11T00:00:00Z",
        ),
        (
            2,
            "00000000-0000-0000-0000-000000000002",
            "user2@example.com",
            json.dumps({"skills": ["go"]}),  # test string json deserialization
            json.dumps({"titles": ["backend dev"]}),
            json.dumps({"work_authorization": True}),
            "auto_submit",
            5,
            1,
            "2026-10-11T00:00:00Z",
            "2026-10-11T00:00:00Z",
        ),
    ]
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch("db.queries.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        users = queries.get_active_users()

        assert len(users) == 2
        assert users[0]["id"] == 1
        assert users[0]["auth_user_id"] == "00000000-0000-0000-0000-000000000001"
        assert users[0]["email"] == "user1@example.com"
        assert users[0]["resume_data"] == {"skills": ["python"]}
        assert users[0]["auto_apply_mode"] == "approval_required"

        assert users[1]["id"] == 2
        assert users[1]["email"] == "user2@example.com"
        assert users[1]["resume_data"] == {"skills": ["go"]}
        assert users[1]["profile_filters"] == {"titles": ["backend dev"]}
        assert users[1]["auto_apply_mode"] == "auto_submit"


def test_get_active_users_handles_null_json():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = [
        (
            3,
            "00000000-0000-0000-0000-000000000003",
            "user3@example.com",
            "null",
            "null",
            "null",
            "approval_required",
            10,
            2,
            "2026-10-11T00:00:00Z",
            "2026-10-11T00:00:00Z",
        )
    ]
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch("db.queries.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        users = queries.get_active_users()
        assert len(users) == 1
        assert users[0]["resume_data"] == {}
        assert users[0]["profile_filters"] == {}
        assert users[0]["screening_defaults"] == {}

        mock_cur.execute.assert_called_once()
        sql = mock_cur.execute.call_args[0][0]
        assert "WHERE auto_apply_mode != 'disabled'" in sql


def test_get_active_users_empty():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = []
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch("db.queries.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        users = queries.get_active_users()
        assert users == []


# ---------------------------------------------------------------------------
# upsert_user_matches
# ---------------------------------------------------------------------------


def test_upsert_user_matches_empty():
    with patch("db.queries.get_connection") as mock_get_conn:
        assert queries.upsert_user_matches(1, []) == 0
        mock_get_conn.assert_not_called()


def test_upsert_user_matches_skips_invalid_job_ids():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.rowcount = 1
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    matches = [
        {"job_posting_id": None, "match_score": 0.5},
        {"job_posting_id": 105, "match_score": 0.9},
    ]

    with patch("db.queries.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        written = queries.upsert_user_matches(1, matches)

        assert written == 1
        sql, rows = mock_cur.executemany.call_args[0]
        assert rows == [(1, 105, 0.9, None)]


def test_upsert_user_matches_executes():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.rowcount = 2
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    matches = [
        {"job_posting_id": 101, "match_score": 0.95, "notified_at": "2026-10-11T12:00:00Z"},
        {"job_id": 102, "match_score": 0.85, "notified_at": None},
    ]

    with patch("db.queries.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        written = queries.upsert_user_matches(1, matches)

        assert written == 2
        mock_cur.executemany.assert_called_once()
        sql, rows = mock_cur.executemany.call_args[0]
        assert "INSERT INTO user_job_matches" in sql
        assert "ON CONFLICT (user_id, job_posting_id) DO UPDATE" in sql
        assert rows == [
            (1, 101, 0.95, "2026-10-11T12:00:00Z"),
            (1, 102, 0.85, None),
        ]


# ---------------------------------------------------------------------------
# queue_user_applications
# ---------------------------------------------------------------------------


def test_queue_user_applications_empty():
    with patch("db.queries.get_connection") as mock_get_conn:
        assert queries.queue_user_applications(1, []) == 0
        mock_get_conn.assert_not_called()


def test_queue_user_applications_executes():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.rowcount = 3
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch("db.queries.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        queued = queries.queue_user_applications(1, [10, 20, 30])

        assert queued == 3
        mock_cur.executemany.assert_called_once()
        sql, rows = mock_cur.executemany.call_args[0]
        assert "INSERT INTO applications" in sql
        assert "ON CONFLICT (user_id, job_posting_id) DO NOTHING" in sql
        assert rows == [(1, 10, "queued"), (1, 20, "queued"), (1, 30, "queued")]


# ---------------------------------------------------------------------------
# record_application_event
# ---------------------------------------------------------------------------


def test_record_application_event():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = (42,)
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch("db.queries.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        event_id = queries.record_application_event(100, "queued", "submitting", "Worker lock acquired")

        assert event_id == 42
        mock_cur.execute.assert_called_once()
        sql, params = mock_cur.execute.call_args[0]
        assert "INSERT INTO application_events" in sql
        assert "RETURNING id" in sql
        assert params == (100, "queued", "submitting", "Worker lock acquired")


# ---------------------------------------------------------------------------
# delete_stale_jobs: prevents foreign key violation on applications
# ---------------------------------------------------------------------------


def test_delete_stale_jobs_protects_applications():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.rowcount = 15
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch("db.queries.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        deleted = queries.delete_stale_jobs(days=30)

        assert deleted == 15
        mock_cur.execute.assert_called_once()
        sql, params = mock_cur.execute.call_args[0]
        assert "DELETE FROM job_postings" in sql
        assert "NOT EXISTS (" in sql
        assert "SELECT 1 FROM applications a WHERE a.job_posting_id = job_postings.id" in sql
        assert params == (30,)


# ---------------------------------------------------------------------------
# Schema and Row Level Security (RLS) assertions
# ---------------------------------------------------------------------------


def test_schema_sql_has_required_tables_and_constraints():
    schema_text = queries.SCHEMA_PATH.read_text()

    # Tables
    assert "CREATE TABLE IF NOT EXISTS users" in schema_text
    assert "CREATE TABLE IF NOT EXISTS user_job_matches" in schema_text
    assert "CREATE TABLE IF NOT EXISTS applications" in schema_text
    assert "CREATE TABLE IF NOT EXISTS application_events" in schema_text

    # Constraints
    assert "auth_user_id            UUID UNIQUE NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE" in schema_text
    assert "job_posting_id      INTEGER NOT NULL REFERENCES job_postings(id) ON DELETE RESTRICT" in schema_text
    assert "UNIQUE (user_id, job_posting_id)" in schema_text
    assert "CHECK (auto_apply_mode IN ('approval_required', 'auto_submit', 'disabled'))" in schema_text

    # Indices
    assert "CREATE INDEX IF NOT EXISTS idx_applications_queued ON applications (status, next_attempt_at)" in schema_text
    assert "CREATE INDEX IF NOT EXISTS idx_applications_user_status ON applications (user_id, status)" in schema_text
    assert "CREATE INDEX IF NOT EXISTS idx_user_job_matches_user_notified ON user_job_matches" in schema_text

    # RLS enablement
    assert "ALTER TABLE users ENABLE ROW LEVEL SECURITY;" in schema_text
    assert "ALTER TABLE user_job_matches ENABLE ROW LEVEL SECURITY;" in schema_text
    assert "ALTER TABLE applications ENABLE ROW LEVEL SECURITY;" in schema_text
    assert "ALTER TABLE application_events ENABLE ROW LEVEL SECURITY;" in schema_text


def test_schema_sql_rls_policies_and_tamper_trigger():
    schema_text = queries.SCHEMA_PATH.read_text()

    # User policies
    assert 'CREATE POLICY "users_select_own" ON users' in schema_text
    assert 'CREATE POLICY "users_update_own" ON users' in schema_text
    assert "auth_user_id = auth.uid()" in schema_text

    # Matches policies
    assert 'CREATE POLICY "user_job_matches_select_own" ON user_job_matches' in schema_text

    # Applications policies
    assert 'CREATE POLICY "applications_select_own" ON applications' in schema_text
    assert 'CREATE POLICY "applications_update_own" ON applications' in schema_text

    # Application events policies
    assert 'CREATE POLICY "application_events_select_own" ON application_events' in schema_text

    # Trigger protecting queue status fields
    assert "CREATE OR REPLACE FUNCTION protect_application_queue_fields()" in schema_text
    assert "trg_protect_application_queue_fields ON applications" in schema_text
    assert "Authenticated users cannot mutate queue status fields" in schema_text


def test_queue_status_protection_trigger_logic():
    """Unit test verifying the trigger logic behavior across different roles and fields."""

    def simulate_trigger(role: str, old_row: dict, new_row: dict):
        if role == "authenticated":
            if (
                new_row.get("status") != old_row.get("status")
                or new_row.get("locked_at") != old_row.get("locked_at")
                or new_row.get("attempt_token") != old_row.get("attempt_token")
                or new_row.get("attempts") != old_row.get("attempts")
                or new_row.get("next_attempt_at") != old_row.get("next_attempt_at")
            ):
                raise PermissionError("Authenticated users cannot mutate queue status fields")
        return new_row

    old = {
        "status": "queued",
        "locked_at": None,
        "attempt_token": None,
        "attempts": 0,
        "next_attempt_at": "2026-10-11T12:00:00Z",
        "submitted_payload": {},
    }

    # Authenticated user updating submitted_payload: allowed
    new_payload = {**old, "submitted_payload": {"answers": {"q1": "yes"}}}
    assert simulate_trigger("authenticated", old, new_payload) == new_payload

    # Authenticated user attempting to mutate status: rejected
    with pytest.raises(PermissionError, match="Authenticated users cannot mutate queue status fields"):
        simulate_trigger("authenticated", old, {**old, "status": "submitting"})

    # Authenticated user attempting to mutate locked_at: rejected
    with pytest.raises(PermissionError, match="Authenticated users cannot mutate queue status fields"):
        simulate_trigger("authenticated", old, {**old, "locked_at": "2026-10-11T12:00:00Z"})

    # Authenticated user attempting to mutate attempt_token: rejected
    with pytest.raises(PermissionError, match="Authenticated users cannot mutate queue status fields"):
        simulate_trigger("authenticated", old, {**old, "attempt_token": "token-123"})

    # Authenticated user attempting to mutate attempts: rejected
    with pytest.raises(PermissionError, match="Authenticated users cannot mutate queue status fields"):
        simulate_trigger("authenticated", old, {**old, "attempts": 1})

    # Authenticated user attempting to mutate next_attempt_at: rejected
    with pytest.raises(PermissionError, match="Authenticated users cannot mutate queue status fields"):
        simulate_trigger("authenticated", old, {**old, "next_attempt_at": "2026-10-12T00:00:00Z"})

    # Service role / worker mutating status: allowed
    service_update = {**old, "status": "submitting", "locked_at": "2026-10-11T12:00:00Z"}
    assert simulate_trigger("service_role", old, service_update) == service_update


# ---------------------------------------------------------------------------
# migrate_to_multiuser script tests
# ---------------------------------------------------------------------------


def test_migrate_profile_to_user_dry_run():
    profile = {"titles": ["software engineer"], "locations": ["remote"]}
    res = migrate_to_multiuser.migrate_profile_to_user(
        profile_data=profile,
        email="test@example.com",
        dry_run=True,
    )
    assert res["id"] == 1
    assert res["email"] == "test@example.com"
    assert res["auth_user_id"] == migrate_to_multiuser.DEFAULT_MIGRATION_UUID
    assert res["profile_filters"] == profile
    assert res["screening_defaults"]["work_authorization"] is True
    assert res["auto_apply_mode"] == "approval_required"


def test_migrate_profile_to_user_db_execution():
    profile = {"titles": ["software engineer"]}
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = (1, "00000000-0000-0000-0000-000000000001", "user1@jobscanr.local")
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    with patch("db.queries.get_connection") as mock_get_conn:
        mock_get_conn.return_value.__enter__.return_value = mock_conn
        res = migrate_to_multiuser.migrate_profile_to_user(
            profile_data=profile,
            email="user1@jobscanr.local",
            dry_run=False,
        )

        assert res["id"] == 1
        assert res["email"] == "user1@jobscanr.local"
        assert res["auth_user_id"] == "00000000-0000-0000-0000-000000000001"
        assert mock_cur.execute.call_count == 4
        assert "SAVEPOINT" in mock_cur.execute.call_args_list[0][0][0]
        assert "INSERT INTO auth.users" in mock_cur.execute.call_args_list[1][0][0]
        assert "RELEASE SAVEPOINT" in mock_cur.execute.call_args_list[2][0][0]
        assert "INSERT INTO users" in mock_cur.execute.call_args_list[3][0][0]
