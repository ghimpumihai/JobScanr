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


def test_users_trigger_refuses_auto_submit():
    fn = SCHEMA[SCHEMA.index("FUNCTION protect_user_worker_fields") :]
    fn = fn[: fn.index("$$ LANGUAGE plpgsql")]
    # No platform accepts applications without the employer's key (#48), so the mode is refused outright.
    assert re.search(
        r"IF NEW\.auto_apply_mode = 'auto_submit' THEN\s+RAISE EXCEPTION 'Automatic submission is not available'", fn
    )
    # The confirmation only enabled auto_submit; its reset and demotion are gone.
    assert "resume_confirmed_at" not in fn
    assert "NEW.auto_apply_mode := 'approval_required'" not in fn
    assert "NEW.max_daily_applications IS NULL OR NEW.max_daily_applications NOT BETWEEN 5 AND 25" in fn
    # The unused worker's claim query still reads the column (D4).
    assert "ALTER TABLE users ADD COLUMN IF NOT EXISTS resume_confirmed_at TIMESTAMPTZ" in SCHEMA


def test_workday_scan_tables_are_backend_only():
    for table in ("workday_board_state", "workday_pod_backoff"):
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in SCHEMA
        assert not re.search(rf"CREATE POLICY [^\n]+ ON {table}", SCHEMA)
    assert "REVOKE ALL ON workday_board_state, workday_pod_backoff FROM anon" in SCHEMA
    assert "REVOKE ALL ON workday_board_state, workday_pod_backoff FROM authenticated" in SCHEMA


def test_applications_status_check_includes_dismissed_for_new_and_existing_databases():
    table = SCHEMA[SCHEMA.index("CREATE TABLE IF NOT EXISTS applications") :]
    table = table[: table.index(");")]
    assert "'dismissed'" in table
    assert "applied_at          TIMESTAMPTZ" in table
    assert "ALTER TABLE applications ADD COLUMN IF NOT EXISTS applied_at TIMESTAMPTZ" in SCHEMA
    # The inline CHECK is named applications_status_check (read on staging, Task 0.3).
    assert "ALTER TABLE applications DROP CONSTRAINT IF EXISTS applications_status_check" in SCHEMA
    added = re.search(r"ADD CONSTRAINT applications_status_check CHECK \(status IN\s*\(([^)]*)\)\)", SCHEMA)
    assert added, "replacement constraint missing"
    assert set(re.findall(r"'(\w+)'", added[1])) == set(re.findall(r"'(\w+)'", table.split("CHECK (status IN", 1)[1]))
    assert {"dismissed", "queued", "submitting"} <= set(re.findall(r"'(\w+)'", added[1]))  # worker statuses kept (D4)


def test_statuses_nothing_can_send_become_manual_apply_with_an_event():
    converted = re.search(
        r"WITH moved AS \(\s*UPDATE applications SET status = 'manual_apply'\s*WHERE status IN \(([^)]*)\)"
        r"\s*RETURNING id\s*\)\s*INSERT INTO application_events \(application_id, from_status, to_status, reason\)"
        r"\s*SELECT id, NULL, 'manual_apply', 'manual_only' FROM moved;",
        SCHEMA,
    )
    assert converted, "conversion statement missing"
    assert set(re.findall(r"'(\w+)'", converted[1])) == {
        "queued",
        "pending_approval",
        "needs_review",
        "failed",
        "submitting",
    }
    assert converted.start() > SCHEMA.index("CREATE TABLE IF NOT EXISTS application_events")
    assert "UPDATE users SET auto_apply_mode = 'approval_required' WHERE auto_apply_mode = 'auto_submit';" in SCHEMA


def _function_body(name: str) -> str:
    body = SCHEMA[SCHEMA.index(f"FUNCTION {name}()") :]
    return body[: body.index("\n$$")]  # the closing $$ starts a line; the opening one ends one


def test_users_may_change_only_the_status_of_an_application():
    fn = _function_body("protect_application_queue_fields")
    assert "current_user = 'authenticated' OR auth.role() = 'authenticated'" in fn
    # Every column but these two is compared, so columns added later are protected too.
    assert "(to_jsonb(NEW) - 'status' - 'applied_at') IS DISTINCT FROM (to_jsonb(OLD) - 'status' - 'applied_at')" in fn
    pairs = set(re.findall(r"\('(\w+)', '(\w+)'\)", fn))
    assert pairs == {
        ("manual_apply", "submitted"),
        ("stale_closed", "submitted"),
        ("manual_apply", "dismissed"),
        ("stale_closed", "dismissed"),
        ("dismissed", "manual_apply"),
    }
    # Undo of Applied only for rows the user marked; the worker never sets applied_at.
    assert "OLD.status = 'submitted' AND NEW.status = 'manual_apply' AND OLD.applied_at IS NOT NULL" in fn
    assert fn.index("NEW.applied_at := NOW()") < fn.index("NEW.applied_at := NULL") < fn.index("ELSE")
    assert "RAISE EXCEPTION 'This status change is not allowed'" in fn.split("ELSE", 1)[1]
    assert "SECURITY DEFINER" not in fn  # runs as the caller, so current_user identifies a web user
    assert re.search(r"CREATE TRIGGER trg_protect_application_queue_fields\s+BEFORE UPDATE ON applications", SCHEMA)
    # Opening a role changes only opened_at, stamped by the database and never cleared (#141).
    opened = "NEW.status = OLD.status AND (to_jsonb(NEW) - 'opened_at') = (to_jsonb(OLD) - 'opened_at')"
    assert opened in fn and "NEW.opened_at := COALESCE(OLD.opened_at, NOW())" in fn
    assert fn.index(opened) < fn.index("(to_jsonb(NEW) - 'status' - 'applied_at')")
    assert "ALTER TABLE applications ADD COLUMN IF NOT EXISTS opened_at TIMESTAMPTZ" in SCHEMA


def test_a_users_status_change_is_logged_by_a_definer_trigger():
    fn = _function_body("log_user_application_change")
    head = SCHEMA[SCHEMA.index("FUNCTION log_user_application_change()") :].split("AS $$", 1)[0]
    assert "SECURITY DEFINER" in head and "SET search_path = ''" in head
    assert "INSERT INTO public.application_events" in fn
    assert "'changed_by_user'" in fn
    trigger = re.search(
        r"CREATE TRIGGER trg_log_user_application_change\s+AFTER UPDATE ON applications\s+FOR EACH ROW\s+"
        r"WHEN \(([^;]+)\)\s+EXECUTE FUNCTION log_user_application_change\(\);",
        SCHEMA,
    )
    assert trigger, "event trigger missing"
    # Checked in WHEN, where current_user is still the caller; inside the definer function it is the owner.
    assert "OLD.status IS DISTINCT FROM NEW.status" in trigger[1]
    assert "current_user = 'authenticated' OR auth.role() = 'authenticated'" in trigger[1]
    assert "REVOKE ALL ON FUNCTION log_user_application_change() FROM PUBLIC" in SCHEMA
    assert "REVOKE ALL ON FUNCTION log_user_application_change() FROM anon, authenticated" in SCHEMA


def test_llm_drafts_are_opt_in_for_new_and_existing_users():
    assert "ALTER TABLE users ADD COLUMN IF NOT EXISTS llm_drafts_enabled BOOLEAN NOT NULL DEFAULT FALSE" in SCHEMA


def test_fill_plans_are_readable_by_their_owner_and_written_only_by_the_backend():
    assert "ALTER TABLE application_fill_plans ENABLE ROW LEVEL SECURITY" in SCHEMA
    policies = re.findall(r'CREATE POLICY "[^"]+" ON application_fill_plans\s+FOR (\w+)', SCHEMA)
    assert policies == ["SELECT"]
    assert "REVOKE ALL ON application_fill_plans, remote_apply_sessions FROM anon" in SCHEMA
    assert "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON application_fill_plans FROM authenticated" in SCHEMA


def test_remote_apply_sessions_are_owned_and_one_open_per_application():
    assert "ALTER TABLE remote_apply_sessions ENABLE ROW LEVEL SECURITY" in SCHEMA
    policies = dict(re.findall(r'CREATE POLICY "([^"]+)" ON remote_apply_sessions\s+FOR (\w+)', SCHEMA))
    assert sorted(policies.values()) == ["INSERT", "SELECT", "UPDATE"]  # no delete
    for name in ("remote_apply_sessions_insert_own", "remote_apply_sessions_update_own"):
        body = SCHEMA[SCHEMA.index(f'CREATE POLICY "{name}"') :].split(";", 1)[0]
        # The row must be the caller's and point at one of the caller's own applications.
        assert "WITH CHECK" in body
        assert "user_id IN (SELECT id FROM users WHERE auth_user_id = auth.uid())" in body
        assert "a.user_id = remote_apply_sessions.user_id" in body
    # Column grants: started_at (what the daily cap counts) can neither be set on insert nor changed later.
    assert "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON remote_apply_sessions FROM authenticated" in SCHEMA
    insert = re.search(r"GRANT INSERT \(([^)]*)\) ON remote_apply_sessions TO authenticated", SCHEMA)
    update = re.search(r"GRANT UPDATE \(([^)]*)\) ON remote_apply_sessions TO authenticated", SCHEMA)
    assert insert and update
    assert {c.strip() for c in insert[1].split(",")} == {"application_id", "user_id", "provider"}
    updatable = {c.strip() for c in update[1].split(",")}
    assert not updatable & {"started_at", "user_id", "application_id", "provider", "id"}
    assert re.search(
        r"CREATE UNIQUE INDEX IF NOT EXISTS uq_remote_apply_sessions_open\s+"
        r"ON remote_apply_sessions \(application_id\) WHERE status = 'open'",
        SCHEMA,
    )
    table = SCHEMA[SCHEMA.index("CREATE TABLE IF NOT EXISTS remote_apply_sessions") :].split(");", 1)[0]
    assert set(re.findall(r"'(\w+)'", table.split("CHECK (status IN", 1)[1])) == {
        "open",
        "submitted",
        "abandoned",
        "expired",
        "error",
        "posting_gone",
    }
    # Never store the live view URL, form values or CV content.
    for column in ("live_view", "url", "values", "resume"):
        assert column not in table


def test_user_answers_are_owned_and_only_their_answer_can_change():
    assert "UNIQUE (user_id, question_key)" in SCHEMA
    assert "answer         TEXT CHECK (answer IS NULL OR char_length(answer) <= 1000)" in SCHEMA
    assert "ALTER TABLE user_answers ENABLE ROW LEVEL SECURITY" in SCHEMA
    policies = re.findall(r'CREATE POLICY "[^"]+" ON user_answers\s+FOR (\w+)', SCHEMA)
    assert sorted(policies) == ["DELETE", "SELECT", "UPDATE"]  # no INSERT: the pipeline adds questions
    assert "REVOKE ALL ON user_answers FROM anon" in SCHEMA
    assert "REVOKE INSERT, UPDATE, TRUNCATE ON user_answers FROM authenticated" in SCHEMA
    assert "GRANT UPDATE (answer, updated_at) ON user_answers TO authenticated" in SCHEMA
