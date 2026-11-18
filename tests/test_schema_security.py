"""Static checks on db/schema.sql security controls (no database needed)."""

import re
from pathlib import Path

SCHEMA = (Path(__file__).resolve().parent.parent / "db" / "schema.sql").read_text()


def test_catalog_tables_have_rls_and_read_only_policies():
    for table in ("companies", "job_postings"):
        assert re.search(rf"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY", SCHEMA)
        assert re.search(
            rf'CREATE POLICY "{table}_select_authenticated" ON {table}\s+FOR SELECT TO authenticated', SCHEMA
        )
        # no write policy may exist for web roles
        assert not re.search(rf"CREATE POLICY [^\n]+ ON {table}\s+FOR (INSERT|UPDATE|DELETE|ALL)", SCHEMA)


def test_catalog_tables_revoked_from_web_roles():
    assert "REVOKE ALL ON companies, job_postings FROM anon" in SCHEMA
    assert "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON companies, job_postings FROM authenticated" in SCHEMA


def test_users_trigger_confines_resume_path_to_owner_folder():
    fn = SCHEMA[SCHEMA.index("FUNCTION protect_user_worker_fields") :]
    fn = fn[: fn.index("$$ LANGUAGE plpgsql")]
    assert "auth.uid() IS NULL" in fn  # NULL uid must fail closed
    assert "position('..' IN NEW.resume_storage_path) > 0" in fn
    assert "split_part(NEW.resume_storage_path, '/', 1) <> auth.uid()::text" in fn
    assert re.search(r"CREATE TRIGGER trg_protect_user_worker_fields\s+BEFORE UPDATE ON users", SCHEMA)


def test_workday_scan_tables_are_backend_only():
    for table in ("workday_board_state", "workday_pod_backoff"):
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in SCHEMA
        assert not re.search(rf"CREATE POLICY [^\n]+ ON {table}", SCHEMA)
    assert "REVOKE ALL ON workday_board_state, workday_pod_backoff FROM anon" in SCHEMA
    assert "REVOKE ALL ON workday_board_state, workday_pod_backoff FROM authenticated" in SCHEMA
