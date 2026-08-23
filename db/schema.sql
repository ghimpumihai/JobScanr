-- JobScanr schema (plan Phase 2)
-- Idempotent: safe to re-run.

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
    UNIQUE (external_id, company_id)
);

CREATE INDEX IF NOT EXISTS idx_job_postings_company ON job_postings (company_id);
CREATE INDEX IF NOT EXISTS idx_job_postings_last_seen ON job_postings (last_seen_at);
