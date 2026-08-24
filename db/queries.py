"""All DB operations in one place (plan Phase 3)."""

from pathlib import Path

import psycopg

from config import DATABASE_URL

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_connection() -> psycopg.Connection:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set — check .env or GitHub secrets")
    return psycopg.connect(DATABASE_URL, autocommit=False)


def apply_schema() -> None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(SCHEMA_PATH.read_text())


def get_all_companies() -> list[dict]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, name, ats_platform, ats_identifier, career_url FROM companies ORDER BY id"
        )
        return [
            {"id": r[0], "name": r[1], "ats_platform": r[2], "ats_identifier": r[3], "career_url": r[4]}
            for r in cur.fetchall()
        ]


def upsert_companies(companies: list[dict]) -> int:
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


def upsert_jobs(jobs: list[dict]) -> list[dict]:
    """Insert jobs for known company_ids.

    Descriptions are deliberately NOT persisted — they're used in memory
    during matching (country restrictions, experience gates) but nothing
    ever reads them back, and they'd dominate storage (~6 KB/row).

    Returns the subset that is genuinely new (first insert), including id.
    """
    if not jobs:
        return []
    cols = ["external_id", "company_id", "title", "location", "department", "url",
            "compensation", "application_deadline"]
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
        RETURNING jp.id, jp.external_id, jp.company_id, (xmax = 0) AS is_new
    """
    out: list[dict] = []
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, arrays)
        for job_id, external_id, company_id, is_new in cur.fetchall():
            if is_new:
                src = next(j for j in jobs
                           if j["external_id"] == external_id and j["company_id"] == company_id)
                out.append({**src, "id": job_id})
    return out


def delete_stale_jobs(days: int = 3) -> int:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "DELETE FROM job_postings WHERE last_seen_at < NOW() - make_interval(days => %s)",
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


def counts() -> dict:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT (SELECT COUNT(*) FROM companies), (SELECT COUNT(*) FROM job_postings)")
        n_companies, n_jobs = cur.fetchone()
        return {"companies": n_companies, "job_postings": n_jobs}
