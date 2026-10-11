-- JobScanr schema (plan Phase 2 & multi-user enhancements)
-- Idempotent: safe to re-run.

-- Ensure auth schema and auth.users stub exist for non-Supabase environments
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.schemata WHERE schema_name = 'auth'
    ) THEN
        EXECUTE 'CREATE SCHEMA auth';
        EXECUTE 'CREATE TABLE auth.users (id UUID PRIMARY KEY, email TEXT)';
    ELSIF NOT EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_schema = 'auth' AND table_name = 'users'
    ) THEN
        EXECUTE 'CREATE TABLE auth.users (id UUID PRIMARY KEY, email TEXT)';
    END IF;
EXCEPTION
    WHEN insufficient_privilege THEN
        NULL; -- Schema auth and auth.users are already managed by Supabase
END $$;

CREATE TABLE IF NOT EXISTS companies (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    ats_platform    TEXT NOT NULL,
    ats_identifier  TEXT NOT NULL,
    career_url      TEXT,
    UNIQUE (ats_platform, ats_identifier)
);

CREATE TABLE IF NOT EXISTS job_postings (
    id              SERIAL PRIMARY KEY,
    external_id     TEXT NOT NULL,
    company_id      INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    location        TEXT,
    department      TEXT,
    url             TEXT,
    -- description intentionally not stored: used only in-memory during matching
    first_seen_at   TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at    TIMESTAMPTZ DEFAULT NOW(),
    notified_at     TIMESTAMPTZ,     -- NULL = not yet included in a digest
    compensation    TEXT,            -- e.g. "€50k–€60k" (Ashby provides it)
    application_deadline TEXT,      -- raw string from the ATS when present
    UNIQUE (external_id, company_id)
);

CREATE INDEX IF NOT EXISTS idx_job_postings_company ON job_postings (company_id);
CREATE INDEX IF NOT EXISTS idx_job_postings_last_seen ON job_postings (last_seen_at);

-- Multi-user tables
CREATE TABLE IF NOT EXISTS users (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    auth_user_id            UUID UNIQUE NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    email                   TEXT UNIQUE NOT NULL,
    resume_data             JSONB NOT NULL DEFAULT '{}'::jsonb,
    profile_filters         JSONB NOT NULL,
    screening_defaults      JSONB NOT NULL,
    auto_apply_mode         TEXT NOT NULL DEFAULT 'approval_required'
                            CHECK (auto_apply_mode IN ('approval_required', 'auto_submit', 'disabled')),
    max_daily_applications  INTEGER DEFAULT 10,
    max_apps_per_company    INTEGER DEFAULT 2,
    gdpr_consent_at         TIMESTAMPTZ NOT NULL,
    created_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_job_matches (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_posting_id  INTEGER NOT NULL REFERENCES job_postings(id) ON DELETE CASCADE,
    match_score     FLOAT,
    notified_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, job_posting_id)
);

CREATE TABLE IF NOT EXISTS applications (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id             BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_posting_id      INTEGER NOT NULL REFERENCES job_postings(id) ON DELETE RESTRICT,
    status              TEXT DEFAULT 'queued'
                        CHECK (status IN ('queued', 'pending_approval', 'submitting', 'submitted', 'needs_review', 'failed', 'manual_apply', 'stale_closed')),
    attempt_token       UUID,
    attempts            INTEGER DEFAULT 0,
    locked_at           TIMESTAMPTZ,
    next_attempt_at     TIMESTAMPTZ DEFAULT NOW(),
    resume_snapshot     JSONB,
    submitted_payload   JSONB,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, job_posting_id)
);

CREATE TABLE IF NOT EXISTS application_events (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    application_id  BIGINT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    from_status     TEXT,
    to_status       TEXT,
    reason          TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Indices for high-throughput queue polling and lookups
CREATE INDEX IF NOT EXISTS idx_applications_queued ON applications (status, next_attempt_at) WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS idx_applications_user_status ON applications (user_id, status);
CREATE INDEX IF NOT EXISTS idx_user_job_matches_user_notified ON user_job_matches (user_id, notified_at);

-- Row Level Security (RLS)
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_job_matches ENABLE ROW LEVEL SECURITY;
ALTER TABLE applications ENABLE ROW LEVEL SECURITY;
ALTER TABLE application_events ENABLE ROW LEVEL SECURITY;

-- Auth helper functions (stubs for local / non-Supabase test environments)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_proc p JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname = 'auth' AND p.proname = 'uid'
    ) THEN
        EXECUTE 'CREATE OR REPLACE FUNCTION auth.uid() RETURNS UUID AS ''SELECT NULLIF(current_setting(''''request.jwt.claim.sub'''', true), '''''''')::uuid;'' LANGUAGE sql STABLE;';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_proc p JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname = 'auth' AND p.proname = 'role'
    ) THEN
        EXECUTE 'CREATE OR REPLACE FUNCTION auth.role() RETURNS TEXT AS ''SELECT COALESCE(NULLIF(current_setting(''''request.jwt.claim.role'''', true), ''''''''), current_user);'' LANGUAGE sql STABLE;';
    END IF;
END $$;

-- Policies for authenticated users
DROP POLICY IF EXISTS "users_select_own" ON users;
CREATE POLICY "users_select_own" ON users
    FOR SELECT TO authenticated
    USING (auth_user_id = auth.uid());

DROP POLICY IF EXISTS "users_update_own" ON users;
CREATE POLICY "users_update_own" ON users
    FOR UPDATE TO authenticated
    USING (auth_user_id = auth.uid())
    WITH CHECK (auth_user_id = auth.uid());

DROP POLICY IF EXISTS "user_job_matches_select_own" ON user_job_matches;
CREATE POLICY "user_job_matches_select_own" ON user_job_matches
    FOR SELECT TO authenticated
    USING (user_id IN (SELECT id FROM users WHERE auth_user_id = auth.uid()));

DROP POLICY IF EXISTS "applications_select_own" ON applications;
CREATE POLICY "applications_select_own" ON applications
    FOR SELECT TO authenticated
    USING (user_id IN (SELECT id FROM users WHERE auth_user_id = auth.uid()));

DROP POLICY IF EXISTS "applications_update_own" ON applications;
CREATE POLICY "applications_update_own" ON applications
    FOR UPDATE TO authenticated
    USING (user_id IN (SELECT id FROM users WHERE auth_user_id = auth.uid()))
    WITH CHECK (user_id IN (SELECT id FROM users WHERE auth_user_id = auth.uid()));

DROP POLICY IF EXISTS "application_events_select_own" ON application_events;
CREATE POLICY "application_events_select_own" ON application_events
    FOR SELECT TO authenticated
    USING (application_id IN (
        SELECT a.id FROM applications a
        JOIN users u ON u.id = a.user_id
        WHERE u.auth_user_id = auth.uid()
    ));

-- Queue status tamper protection trigger for applications
CREATE OR REPLACE FUNCTION protect_application_queue_fields()
RETURNS TRIGGER AS $$
BEGIN
    IF (current_user = 'authenticated' OR auth.role() = 'authenticated') THEN
        IF (NEW.status IS DISTINCT FROM OLD.status) OR
           (NEW.locked_at IS DISTINCT FROM OLD.locked_at) OR
           (NEW.attempt_token IS DISTINCT FROM OLD.attempt_token) OR
           (NEW.attempts IS DISTINCT FROM OLD.attempts) OR
           (NEW.next_attempt_at IS DISTINCT FROM OLD.next_attempt_at) THEN
            RAISE EXCEPTION 'Authenticated users cannot mutate queue status fields';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_protect_application_queue_fields ON applications;
CREATE TRIGGER trg_protect_application_queue_fields
    BEFORE UPDATE ON applications
    FOR EACH ROW
    EXECUTE FUNCTION protect_application_queue_fields();
