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

-- Workday scan cache (backend only), so unchanged boards cost one request instead of up to eleven.
-- queries: {query_key: {total, first_ids, postings: [listing rows, never descriptions]}}
-- enrichment: {external_id: {at, location, url, compensation, application_deadline, verdicts: {profile_hash: bool}}}
CREATE TABLE IF NOT EXISTS workday_board_state (
    company_id      INTEGER PRIMARY KEY REFERENCES companies(id) ON DELETE CASCADE,
    queries         JSONB NOT NULL DEFAULT '{}'::jsonb,
    enrichment      JSONB NOT NULL DEFAULT '{}'::jsonb,
    full_scan_at    TIMESTAMPTZ,
    last_candidate_at TIMESTAMPTZ,      -- last run a posting passed the prefilter; NULL/old = scanned weekly only
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Per Workday pod (wd1.myworkdayjobs.com, ...) that answered with a Cloudflare challenge: no requests until
-- challenged_until, then one probe; a challenged probe backs off again for the same backoff_days.
CREATE TABLE IF NOT EXISTS workday_pod_backoff (
    pod              TEXT PRIMARY KEY,
    challenged_until TIMESTAMPTZ NOT NULL,
    backoff_days     INTEGER NOT NULL
);

-- Multi-user tables
CREATE TABLE IF NOT EXISTS users (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    auth_user_id            UUID UNIQUE NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    email                   TEXT UNIQUE NOT NULL,
    resume_storage_path     TEXT,
    resume_filename         TEXT,
    resume_content_type     TEXT,
    resume_uploaded_at      TIMESTAMPTZ,
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

-- Idempotent column migrations for existing deployments
ALTER TABLE users ADD COLUMN IF NOT EXISTS resume_storage_path TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS resume_filename TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS resume_content_type TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS resume_uploaded_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS resume_confirmed_at TIMESTAMPTZ;

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
                        CHECK (status IN ('queued', 'pending_approval', 'submitting', 'submitted', 'needs_review', 'failed', 'manual_apply', 'stale_closed', 'dismissed')),
    attempt_token       UUID,
    attempts            INTEGER DEFAULT 0,
    locked_at           TIMESTAMPTZ,
    next_attempt_at     TIMESTAMPTZ DEFAULT NOW(),
    resume_snapshot     JSONB,
    submitted_payload   JSONB,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    applied_at          TIMESTAMPTZ,     -- set only by protect_application_queue_fields when the user marks it applied
    UNIQUE (user_id, job_posting_id)
);

ALTER TABLE applications ADD COLUMN IF NOT EXISTS applied_at TIMESTAMPTZ;
-- PostgreSQL named the inline CHECK above applications_status_check. Replaced so existing databases accept
-- 'dismissed'; the worker's statuses stay allowed while its code is kept (#48, D4).
ALTER TABLE applications DROP CONSTRAINT IF EXISTS applications_status_check;
ALTER TABLE applications ADD CONSTRAINT applications_status_check CHECK (status IN
    ('queued', 'pending_approval', 'submitting', 'submitted', 'needs_review', 'failed', 'manual_apply',
     'stale_closed', 'dismissed'));

CREATE TABLE IF NOT EXISTS application_events (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    application_id  BIGINT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    from_status     TEXT,
    to_status       TEXT,
    reason          TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Greenhouse and Lever accept applications only with the employer's API key (#48, Task 0.2), so nothing is
-- ever sent and every application is applied to by hand. Rows in a sending status are moved to manual_apply on
-- every schema run. Remove this before reviving the apply worker, or it would undo the worker's queue.
WITH moved AS (
    UPDATE applications SET status = 'manual_apply'
    WHERE status IN ('queued', 'pending_approval', 'needs_review', 'failed', 'submitting')
    RETURNING id
)
INSERT INTO application_events (application_id, from_status, to_status, reason)
SELECT id, NULL, 'manual_apply', 'manual_only' FROM moved;

UPDATE users SET auto_apply_mode = 'approval_required' WHERE auto_apply_mode = 'auto_submit';

-- Remote-browser apply spike (#129). Fill plans are built by the pipeline (backend only) from the public
-- Greenhouse question schema; a user may read their own. Sessions hold per-session metrics, never the live
-- view URL, form values or CV content.
CREATE TABLE IF NOT EXISTS application_fill_plans (
    application_id  BIGINT PRIMARY KEY REFERENCES applications(id) ON DELETE CASCADE,
    plan            JSONB NOT NULL,
    built_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS remote_apply_sessions (
    id                      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    application_id          BIGINT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    user_id                 BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider                TEXT NOT NULL,
    provider_session_id     TEXT,
    status                  TEXT NOT NULL DEFAULT 'open'
                            CHECK (status IN ('open', 'submitted', 'abandoned', 'expired', 'error', 'posting_gone')),
    fields_planned          INTEGER,
    fields_filled           INTEGER,
    fields_unfilled         INTEGER,
    fields_changed_by_user  INTEGER,
    captcha_seen            BOOLEAN NOT NULL DEFAULT FALSE,
    error                   TEXT,
    started_at              TIMESTAMPTZ DEFAULT NOW(),
    ended_at                TIMESTAMPTZ
);

-- One open session per application, so two tabs cannot fill the same form twice.
CREATE UNIQUE INDEX IF NOT EXISTS uq_remote_apply_sessions_open
    ON remote_apply_sessions (application_id) WHERE status = 'open';
-- The daily cap counts a user's sessions since midnight.
CREATE INDEX IF NOT EXISTS idx_remote_apply_sessions_user_started ON remote_apply_sessions (user_id, started_at);

-- Indices for high-throughput queue polling and lookups
CREATE INDEX IF NOT EXISTS idx_applications_queued ON applications (status, next_attempt_at) WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS idx_applications_user_status ON applications (user_id, status);
CREATE INDEX IF NOT EXISTS idx_user_job_matches_user_notified ON user_job_matches (user_id, notified_at);

-- Row Level Security (RLS)
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_job_matches ENABLE ROW LEVEL SECURITY;
ALTER TABLE applications ENABLE ROW LEVEL SECURITY;
ALTER TABLE application_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE application_fill_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE remote_apply_sessions ENABLE ROW LEVEL SECURITY;

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

-- Fill plans: read own, never written by web roles (no write policy; writes also revoked below).
DROP POLICY IF EXISTS "application_fill_plans_select_own" ON application_fill_plans;
CREATE POLICY "application_fill_plans_select_own" ON application_fill_plans
    FOR SELECT TO authenticated
    USING (application_id IN (
        SELECT a.id FROM applications a
        JOIN users u ON u.id = a.user_id
        WHERE u.auth_user_id = auth.uid()
    ));

-- Remote apply sessions: the web app writes them with the user's own session. A row must belong to the
-- caller and point at one of the caller's applications. Users can edit their own metrics; accepted for the
-- spike's <= 5-user pilot (plan 2.1). No delete policy.
DROP POLICY IF EXISTS "remote_apply_sessions_select_own" ON remote_apply_sessions;
CREATE POLICY "remote_apply_sessions_select_own" ON remote_apply_sessions
    FOR SELECT TO authenticated
    USING (user_id IN (SELECT id FROM users WHERE auth_user_id = auth.uid()));

DROP POLICY IF EXISTS "remote_apply_sessions_insert_own" ON remote_apply_sessions;
CREATE POLICY "remote_apply_sessions_insert_own" ON remote_apply_sessions
    FOR INSERT TO authenticated
    WITH CHECK (
        user_id IN (SELECT id FROM users WHERE auth_user_id = auth.uid())
        AND application_id IN (SELECT a.id FROM applications a WHERE a.user_id = remote_apply_sessions.user_id)
    );

DROP POLICY IF EXISTS "remote_apply_sessions_update_own" ON remote_apply_sessions;
CREATE POLICY "remote_apply_sessions_update_own" ON remote_apply_sessions
    FOR UPDATE TO authenticated
    USING (user_id IN (SELECT id FROM users WHERE auth_user_id = auth.uid()))
    WITH CHECK (
        user_id IN (SELECT id FROM users WHERE auth_user_id = auth.uid())
        AND application_id IN (SELECT a.id FROM applications a WHERE a.user_id = remote_apply_sessions.user_id)
    );

-- applications: a signed-in user (applications_update_own limits them to their own rows) may only move an
-- application between To Apply, Applied and Not Interested, and back (#48). Every other column, including ones
-- added later, is compared and must stay unchanged. applied_at is set here, never by the user. Backend writes
-- (the pipeline, the unused worker) are not 'authenticated' and pass unchanged.
CREATE OR REPLACE FUNCTION protect_application_queue_fields()
RETURNS TRIGGER AS $$
BEGIN
    IF (current_user = 'authenticated' OR auth.role() = 'authenticated') THEN
        IF (to_jsonb(NEW) - 'status' - 'applied_at') IS DISTINCT FROM (to_jsonb(OLD) - 'status' - 'applied_at') THEN
            RAISE EXCEPTION 'Only the application status can be changed';
        END IF;
        IF (OLD.status, NEW.status) IN (('manual_apply', 'submitted'), ('stale_closed', 'submitted')) THEN
            NEW.applied_at := NOW();
        ELSIF (OLD.status, NEW.status) IN (('manual_apply', 'dismissed'), ('stale_closed', 'dismissed'),
                                           ('dismissed', 'manual_apply'))
           OR (OLD.status = 'submitted' AND NEW.status = 'manual_apply' AND OLD.applied_at IS NOT NULL) THEN
            NEW.applied_at := NULL;
        ELSE
            -- also an unchanged status, so applied_at cannot be set on its own
            RAISE EXCEPTION 'This status change is not allowed';
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

-- Web users cannot insert events (no policy), so a definer function records their changes. Backend writes
-- record their own events. The caller is checked in WHEN, where current_user is still the caller.
CREATE OR REPLACE FUNCTION log_user_application_change()
RETURNS TRIGGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
    INSERT INTO public.application_events (application_id, from_status, to_status, reason)
    VALUES (NEW.id, OLD.status, NEW.status, 'changed_by_user');
    RETURN NULL;
END;
$$;

REVOKE ALL ON FUNCTION log_user_application_change() FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON FUNCTION log_user_application_change() FROM anon, authenticated;
    END IF;
END $$;

DROP TRIGGER IF EXISTS trg_log_user_application_change ON applications;
CREATE TRIGGER trg_log_user_application_change
    AFTER UPDATE ON applications
    FOR EACH ROW
    WHEN (OLD.status IS DISTINCT FROM NEW.status AND (current_user = 'authenticated' OR auth.role() = 'authenticated'))
    EXECUTE FUNCTION log_user_application_change();

-- Shared catalog tables (companies, job_postings): written only by the backend, which connects with a
-- role that bypasses RLS. Authenticated web users may read them (the matches page joins job_postings);
-- anon gets nothing and no web role can write. Without this, Supabase's default grants expose them
-- to writes through the public anon key.
ALTER TABLE companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_postings ENABLE ROW LEVEL SECURITY;
-- workday_board_state: RLS on and no policies, so web roles can neither read nor write it.
ALTER TABLE workday_board_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE workday_pod_backoff ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "companies_select_authenticated" ON companies;
CREATE POLICY "companies_select_authenticated" ON companies
    FOR SELECT TO authenticated
    USING (true);

DROP POLICY IF EXISTS "job_postings_select_authenticated" ON job_postings;
CREATE POLICY "job_postings_select_authenticated" ON job_postings
    FOR SELECT TO authenticated
    USING (true);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON companies, job_postings FROM anon;
        REVOKE ALL ON workday_board_state, workday_pod_backoff FROM anon;
        REVOKE ALL ON application_fill_plans, remote_apply_sessions FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON companies, job_postings FROM authenticated;
        REVOKE ALL ON workday_board_state, workday_pod_backoff FROM authenticated;
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON application_fill_plans FROM authenticated;
        REVOKE DELETE, TRUNCATE ON remote_apply_sessions FROM authenticated;
    END IF;
EXCEPTION
    WHEN insufficient_privilege THEN
        NULL;
END $$;

-- users: the apply worker downloads users.resume_storage_path with the service-role key (which bypasses
-- storage RLS), so a user may only point it at their own folder in the resumes bucket. Users can update their
-- own row with the public anon key, so these rules are enforced here, not in the UI. auto_submit is refused:
-- Greenhouse and Lever accept applications only with the employer's API key (#48), so nothing can be sent.
CREATE OR REPLACE FUNCTION protect_user_worker_fields()
RETURNS TRIGGER AS $$
BEGIN
    IF (current_user = 'authenticated' OR auth.role() = 'authenticated') THEN
        IF NEW.resume_storage_path IS DISTINCT FROM OLD.resume_storage_path
           AND NEW.resume_storage_path IS NOT NULL THEN
            IF auth.uid() IS NULL
               OR position('..' IN NEW.resume_storage_path) > 0
               OR position('/' IN NEW.resume_storage_path) = 0
               OR split_part(NEW.resume_storage_path, '/', 1) <> auth.uid()::text THEN
                RAISE EXCEPTION 'resume_storage_path must be inside your own folder';
            END IF;
        END IF;
        IF NEW.auto_apply_mode = 'auto_submit' THEN
            RAISE EXCEPTION 'Automatic submission is not available';
        END IF;
        IF NEW.max_daily_applications IS DISTINCT FROM OLD.max_daily_applications
           AND (NEW.max_daily_applications IS NULL OR NEW.max_daily_applications NOT BETWEEN 5 AND 25) THEN
            RAISE EXCEPTION 'max_daily_applications must be between 5 and 25';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_protect_user_worker_fields ON users;
CREATE TRIGGER trg_protect_user_worker_fields
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION protect_user_worker_fields();

-- Supabase Storage 'resumes' bucket definition (idempotent, safe for non-Supabase environments)
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.schemata WHERE schema_name = 'storage'
    ) AND EXISTS (
        SELECT 1 FROM information_schema.tables WHERE table_schema = 'storage' AND table_name = 'buckets'
    ) THEN
        INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
        VALUES (
            'resumes',
            'resumes',
            false,
            2097152, -- 2 MB
            ARRAY[
                'application/pdf',
                'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                'application/msword'
            ]
        )
        ON CONFLICT (id) DO UPDATE SET
            file_size_limit = EXCLUDED.file_size_limit,
            allowed_mime_types = EXCLUDED.allowed_mime_types;

        -- RLS Policies on storage.objects for authenticated users
        IF EXISTS (
            SELECT 1 FROM information_schema.tables WHERE table_schema = 'storage' AND table_name = 'objects'
        ) THEN
            DROP POLICY IF EXISTS "resumes_insert_own" ON storage.objects;
            CREATE POLICY "resumes_insert_own" ON storage.objects
                FOR INSERT TO authenticated
                WITH CHECK (
                    bucket_id = 'resumes' AND
                    (storage.foldername(name))[1] = (auth.uid())::text
                );

            DROP POLICY IF EXISTS "resumes_select_own" ON storage.objects;
            CREATE POLICY "resumes_select_own" ON storage.objects
                FOR SELECT TO authenticated
                USING (
                    bucket_id = 'resumes' AND
                    (storage.foldername(name))[1] = (auth.uid())::text
                );

            DROP POLICY IF EXISTS "resumes_update_own" ON storage.objects;
            CREATE POLICY "resumes_update_own" ON storage.objects
                FOR UPDATE TO authenticated
                USING (
                    bucket_id = 'resumes' AND
                    (storage.foldername(name))[1] = (auth.uid())::text
                );

            DROP POLICY IF EXISTS "resumes_delete_own" ON storage.objects;
            CREATE POLICY "resumes_delete_own" ON storage.objects
                FOR DELETE TO authenticated
                USING (
                    bucket_id = 'resumes' AND
                    (storage.foldername(name))[1] = (auth.uid())::text
                );
        END IF;
    END IF;
EXCEPTION
    WHEN insufficient_privilege THEN
        NULL;
    WHEN undefined_function THEN
        NULL;
    WHEN undefined_table THEN
        NULL;
END $$;

