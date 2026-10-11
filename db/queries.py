"""All DB operations in one place (plan Phase 3)."""

import json
from contextlib import AbstractContextManager
from pathlib import Path

import psycopg
from psycopg_pool import ConnectionPool

import config
from models import Company, JobPosting

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

_pool: ConnectionPool | None = None
_pool_conninfo: str | None = None


def get_pool() -> ConnectionPool:
    global _pool, _pool_conninfo
    database_url = getattr(config, "DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set — check .env or GitHub secrets")
    if _pool is None or _pool.closed or _pool_conninfo != database_url:
        if _pool is not None and not _pool.closed:
            _pool.close()
        _pool = ConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=10,
            open=True,
        )
        _pool_conninfo = database_url
    return _pool


def close_pool() -> None:
    global _pool, _pool_conninfo
    if _pool is not None and not _pool.closed:
        _pool.close()
    _pool = None
    _pool_conninfo = None


def get_connection(timeout: float | None = None) -> AbstractContextManager[psycopg.Connection]:
    return get_pool().connection(timeout=timeout)


def apply_schema() -> None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(SCHEMA_PATH.read_text())


def get_all_companies() -> list[Company]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, name, ats_platform, ats_identifier, career_url FROM companies ORDER BY id")
        return [
            {"id": r[0], "name": r[1], "ats_platform": r[2], "ats_identifier": r[3], "career_url": r[4]}
            for r in cur.fetchall()
        ]


def upsert_companies(companies: list[Company | dict]) -> int:
    """Idempotent seed. Returns number of rows written."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO companies (name, ats_platform, ats_identifier, career_url)
            VALUES (%(company_name)s, %(ats_platform)s, %(ats_identifier)s, %(career_url)s)
            ON CONFLICT (ats_platform, ats_identifier) DO UPDATE
                SET name = EXCLUDED.name,
                    career_url = EXCLUDED.career_url
            """,
            companies,
        )
        return cur.rowcount


def upsert_jobs(jobs: list[JobPosting | dict]) -> list[JobPosting]:
    """Insert jobs for known company_ids.

    Descriptions are deliberately NOT persisted — they're used in memory
    during matching (country restrictions, experience gates) but nothing
    ever reads them back, and they'd dominate storage (~6 KB/row).

    Returns the subset that is genuinely new (first insert), including id.
    """
    if not jobs:
        return []
    cols = [
        "external_id",
        "company_id",
        "title",
        "location",
        "department",
        "url",
        "compensation",
        "application_deadline",
    ]
    arrays = {c: [j.get(c) for j in jobs] for c in cols}
    sql = """
        INSERT INTO job_postings AS jp (external_id, company_id, title, location, department, url,
                                        compensation, application_deadline)
        SELECT * FROM unnest(
            %(external_id)s::text[], %(company_id)s::int[], %(title)s::text[],
            %(location)s::text[], %(department)s::text[], %(url)s::text[],
            %(compensation)s::text[], %(application_deadline)s::text[]
        )
        ON CONFLICT (external_id, company_id) DO UPDATE
            SET last_seen_at = NOW(),
                title = EXCLUDED.title,
                location = EXCLUDED.location,
                department = EXCLUDED.department,
                url = EXCLUDED.url,
                compensation = EXCLUDED.compensation,
                application_deadline = EXCLUDED.application_deadline
        RETURNING jp.id, jp.external_id, jp.company_id, (jp.first_seen_at = jp.last_seen_at) AS is_new
    """
    job_map = {(j["external_id"], j["company_id"]): j for j in jobs}
    out: list[dict] = []
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, arrays)
        for job_id, external_id, company_id, is_new in cur.fetchall():
            if is_new:
                src = job_map.get((external_id, company_id))
                if src is not None:
                    out.append({**src, "id": job_id})
    return out


def delete_stale_jobs(days: int = 30) -> int:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM job_postings
            WHERE last_seen_at < NOW() - make_interval(days => %s)
              AND NOT EXISTS (
                  SELECT 1 FROM applications a WHERE a.job_posting_id = job_postings.id
              )
            """,
            (days,),
        )
        return cur.rowcount


def mark_notified(job_ids: list[int]) -> None:
    if not job_ids:
        return
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE job_postings SET notified_at = NOW() WHERE id = ANY(%s::int[])",
            (job_ids,),
        )


def delete_company(ats_platform: str, ats_identifier: str) -> int:
    """Delete a single company by ATS platform and identifier. Cascades to job_postings."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM companies WHERE ats_platform = %s AND ats_identifier = %s",
            (ats_platform, ats_identifier),
        )
        return cur.rowcount


def delete_companies_batch(identifiers: list[tuple[str, str]]) -> int:
    """Delete multiple companies by (ats_platform, ats_identifier). Cascades to job_postings."""
    if not identifiers:
        return 0
    with get_connection() as conn, conn.cursor() as cur:
        cur.executemany(
            "DELETE FROM companies WHERE ats_platform = %s AND ats_identifier = %s",
            identifiers,
        )
        return cur.rowcount


def counts() -> dict:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT (SELECT COUNT(*) FROM companies), (SELECT COUNT(*) FROM job_postings)")
        n_companies, n_jobs = cur.fetchone()
        return {"companies": n_companies, "job_postings": n_jobs}


def prune_obsolete_companies(valid_keys: set[tuple[str, str]]) -> list[Company]:
    """Delete companies not present in valid_keys. Cascades to job_postings.

    Returns the list of deleted company metadata dicts.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, name, ats_platform, ats_identifier FROM companies")
        to_delete = []
        deleted_records = []
        for row in cur.fetchall():
            if (row[2], row[3]) not in valid_keys:
                to_delete.append(row[0])
                deleted_records.append(
                    {
                        "id": row[0],
                        "name": row[1],
                        "ats_platform": row[2],
                        "ats_identifier": row[3],
                    }
                )
        if to_delete:
            cur.execute("DELETE FROM companies WHERE id = ANY(%s)", (to_delete,))
        return deleted_records


def get_recent_job_samples(limit: int = 5) -> list[dict]:
    """Fetch sample of recent job postings for previews/testing."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT jp.title, c.name AS company_name, jp.location, jp.url
               FROM job_postings jp JOIN companies c ON c.id = jp.company_id
               ORDER BY jp.first_seen_at DESC
               LIMIT %s""",
            (limit,),
        )
        return [dict(zip(("title", "company_name", "location", "url"), r)) for r in cur.fetchall()]


def get_active_users() -> list[dict]:
    """Fetch all users whose auto_apply_mode is not disabled."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, auth_user_id, email, resume_data, profile_filters, screening_defaults,
                   auto_apply_mode, max_daily_applications, max_apps_per_company, gdpr_consent_at, created_at
            FROM users
            WHERE auto_apply_mode != 'disabled'
            ORDER BY id
            """
        )
        users = []
        for r in cur.fetchall():
            resume_data = (r[3] if isinstance(r[3], dict) else (json.loads(r[3]) if r[3] else {})) or {}
            profile_filters = (r[4] if isinstance(r[4], dict) else (json.loads(r[4]) if r[4] else {})) or {}
            screening_defaults = (r[5] if isinstance(r[5], dict) else (json.loads(r[5]) if r[5] else {})) or {}
            users.append(
                {
                    "id": r[0],
                    "auth_user_id": str(r[1]),
                    "email": r[2],
                    "resume_data": resume_data,
                    "profile_filters": profile_filters,
                    "screening_defaults": screening_defaults,
                    "auto_apply_mode": r[6],
                    "max_daily_applications": r[7],
                    "max_apps_per_company": r[8],
                    "gdpr_consent_at": r[9],
                    "created_at": r[10],
                }
            )
        return users


def upsert_user_matches(user_id: int, matches: list[dict]) -> int:
    """Upsert match scores and notification timestamps for a user."""
    if not matches:
        return 0
    rows = []
    for m in matches:
        job_id = m.get("job_posting_id") or m.get("job_id") or m.get("id")
        if not job_id:
            continue
        score = m.get("match_score")
        notified = m.get("notified_at")
        rows.append((user_id, job_id, score, notified))

    if not rows:
        return 0

    with get_connection() as conn, conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO user_job_matches (user_id, job_posting_id, match_score, notified_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, job_posting_id) DO UPDATE
                SET match_score = COALESCE(EXCLUDED.match_score, user_job_matches.match_score),
                    notified_at = COALESCE(EXCLUDED.notified_at, user_job_matches.notified_at)
            """,
            rows,
        )
        return cur.rowcount


def queue_user_applications(user_id: int, job_ids: list[int]) -> int:
    """Queue application submissions for a user (skips already existing)."""
    if not job_ids:
        return 0
    with get_connection() as conn, conn.cursor() as cur:
        rows = [(user_id, jid) for jid in job_ids]
        cur.executemany(
            """
            INSERT INTO applications (user_id, job_posting_id, status)
            VALUES (%s, %s, 'queued')
            ON CONFLICT (user_id, job_posting_id) DO NOTHING
            """,
            rows,
        )
        return cur.rowcount


def record_application_event(app_id: int, from_status: str | None, to_status: str, reason: str | None = None) -> int:
    """Record an immutable audit event for an application status change."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO application_events (application_id, from_status, to_status, reason)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (app_id, from_status, to_status, reason),
        )
        row = cur.fetchone()
        return row[0] if row else 0
