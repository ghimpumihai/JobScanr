"""All DB operations in one place (plan Phase 3)."""

import json
import logging
import uuid
from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg_pool import ConnectionPool

import config
from models import Company, JobPosting

logger = logging.getLogger(__name__)

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


def upsert_jobs(jobs: list[JobPosting]) -> list[JobPosting]:
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
    out: list[JobPosting] = []
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, arrays)
        for job_id, external_id, company_id, is_new in cur.fetchall():
            src = job_map.get((external_id, company_id))
            if src is not None:
                src["id"] = job_id
                if is_new:
                    out.append(src)
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


def close_unlisted_applications(days: int = 30) -> int:
    """Move To Apply rows whose posting the scanner has not seen for `days` to stale_closed, one event each.

    Uses the same age as delete_stale_jobs, which keeps these postings only because applications reference them.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            WITH closed AS (
                UPDATE applications a SET status = 'stale_closed'
                FROM job_postings jp
                WHERE jp.id = a.job_posting_id AND a.status = 'manual_apply'
                  AND jp.last_seen_at < NOW() - make_interval(days => %s)
                RETURNING a.id
            )
            INSERT INTO application_events (application_id, from_status, to_status, reason)
            SELECT id, 'manual_apply', 'stale_closed', 'posting_unlisted' FROM closed
            """,
            (days,),
        )
        return cur.rowcount


def get_workday_board_states() -> dict[int, dict]:
    """Cached Workday scan state per company_id (see workday_board_state in db/schema.sql)."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT company_id, queries, enrichment, full_scan_at, last_candidate_at FROM workday_board_state")
        return {
            cid: {
                "queries": q or {},
                "enrichment": e or {},
                "full_scan_at": f.isoformat() if f else None,
                "last_candidate_at": lc.isoformat() if lc else None,
            }
            for cid, q, e, f, lc in cur.fetchall()
        }


def save_workday_board_states(states: dict[int, dict]) -> int:
    if not states:
        return 0
    rows = [
        (
            cid,
            json.dumps(s.get("queries") or {}),
            json.dumps(s.get("enrichment") or {}),
            s.get("full_scan_at"),
            s.get("last_candidate_at"),
        )
        for cid, s in states.items()
    ]
    with get_connection() as conn, conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO workday_board_state
                (company_id, queries, enrichment, full_scan_at, last_candidate_at, updated_at)
            VALUES (%s, %s::jsonb, %s::jsonb, %s::timestamptz, %s::timestamptz, NOW())
            ON CONFLICT (company_id) DO UPDATE
                SET queries = EXCLUDED.queries,
                    enrichment = EXCLUDED.enrichment,
                    full_scan_at = EXCLUDED.full_scan_at,
                    last_candidate_at = EXCLUDED.last_candidate_at,
                    updated_at = NOW()
            """,
            rows,
        )
        return len(rows)


def get_workday_pod_backoff() -> dict[str, dict]:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT pod, challenged_until, backoff_days FROM workday_pod_backoff")
        return {pod: {"until": until, "days": days} for pod, until, days in cur.fetchall()}


def save_workday_pod_backoff(upserts: dict[str, dict], deletes: set[str]) -> None:
    with get_connection() as conn, conn.cursor() as cur:
        if upserts:
            cur.executemany(
                """
                INSERT INTO workday_pod_backoff (pod, challenged_until, backoff_days) VALUES (%s, %s, %s)
                ON CONFLICT (pod) DO UPDATE
                    SET challenged_until = EXCLUDED.challenged_until, backoff_days = EXCLUDED.backoff_days
                """,
                [(pod, v["until"], v["days"]) for pod, v in upserts.items()],
            )
        if deletes:
            cur.execute("DELETE FROM workday_pod_backoff WHERE pod = ANY(%s)", (list(deletes),))


def get_unnotified_jobs(max_age_days: int = 7) -> list[dict]:
    """Stored jobs not yet in a digest (single-user mode), newest first.

    The age bound keeps a long-failed mail setup from flushing a stale backlog in one digest.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT jp.id, jp.title, c.name AS company_name, jp.location, jp.url,
                   jp.compensation, jp.application_deadline, c.ats_platform
            FROM job_postings jp
            JOIN companies c ON c.id = jp.company_id
            WHERE jp.notified_at IS NULL AND jp.first_seen_at > NOW() - make_interval(days => %s)
            ORDER BY jp.first_seen_at DESC
            """,
            (max_age_days,),
        )
        cols = (
            "id",
            "title",
            "company_name",
            "location",
            "url",
            "compensation",
            "application_deadline",
            "ats_platform",
        )
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def mark_notified(job_ids: list[int]) -> None:
    if not job_ids:
        return
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE job_postings SET notified_at = NOW() WHERE id = ANY(%s::int[])",
            (job_ids,),
        )


# Companies whose postings have applications are kept: applications.job_posting_id is ON DELETE RESTRICT,
# so deleting one fails and rolls back the whole batch (no company gets pruned).
_COMPANY_HAS_APPLICATIONS = """EXISTS (
    SELECT 1 FROM job_postings jp JOIN applications a ON a.job_posting_id = jp.id
    WHERE jp.company_id = companies.id
)"""
_DELETE_COMPANY_SQL = (
    "DELETE FROM companies WHERE ats_platform = %s AND ats_identifier = %s AND NOT " + _COMPANY_HAS_APPLICATIONS
)


def delete_company(ats_platform: str, ats_identifier: str) -> int:
    """Delete a single company by ATS platform and identifier. Cascades to job_postings."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(_DELETE_COMPANY_SQL, (ats_platform, ats_identifier))
        return cur.rowcount


def delete_companies_batch(identifiers: list[tuple[str, str]]) -> int:
    """Delete multiple companies by (ats_platform, ats_identifier). Cascades to job_postings."""
    if not identifiers:
        return 0
    with get_connection() as conn, conn.cursor() as cur:
        cur.executemany(_DELETE_COMPANY_SQL, identifiers)
        return cur.rowcount


def counts() -> dict:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT (SELECT COUNT(*) FROM companies), (SELECT COUNT(*) FROM job_postings)")
        row = cur.fetchone()
        assert row is not None  # two scalar subqueries always return exactly one row
        n_companies, n_jobs = row
        return {"companies": n_companies, "job_postings": n_jobs}


def prune_obsolete_companies(valid_keys: set[tuple[str, str]]) -> list[Company]:
    """Delete companies not present in valid_keys. Cascades to job_postings.

    Returns the list of deleted company metadata dicts.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, name, ats_platform, ats_identifier FROM companies WHERE NOT " + _COMPANY_HAS_APPLICATIONS
        )
        to_delete = []
        deleted_records: list[Company] = []
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
                   auto_apply_mode, max_daily_applications, max_apps_per_company, gdpr_consent_at, created_at,
                   resume_storage_path, resume_filename, resume_content_type, resume_uploaded_at,
                   llm_drafts_enabled
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
                    "resume_storage_path": r[11] if len(r) > 11 else None,
                    "resume_filename": r[12] if len(r) > 12 else None,
                    "resume_content_type": r[13] if len(r) > 13 else None,
                    "resume_uploaded_at": r[14] if len(r) > 14 else None,
                    "llm_drafts_enabled": bool(r[15]) if len(r) > 15 else False,
                }
            )
        return users


def update_user_resume_metadata(
    user_id: int,
    storage_path: str,
    filename: str,
    content_type: str,
) -> bool:
    """Update user's active resume file metadata and upload timestamp."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE users
            SET resume_storage_path = %s,
                resume_filename = %s,
                resume_content_type = %s,
                resume_uploaded_at = NOW()
            WHERE id = %s
            """,
            (storage_path, filename, content_type, user_id),
        )
        return cur.rowcount > 0


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


def stage_user_applications(user_id: int, items: list[dict]) -> int:
    """Stage applications with specific status (skips already existing)."""
    if not items:
        return 0
    rows = []
    for it in items:
        jid = it.get("job_posting_id") or it.get("job_id") or it.get("id")
        status = it.get("status", "queued")
        if jid:
            rows.append((user_id, jid, status))
    if not rows:
        return 0
    with get_connection() as conn, conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO applications (user_id, job_posting_id, status)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, job_posting_id) DO NOTHING
            """,
            rows,
        )
        return cur.rowcount


def queue_user_applications(user_id: int, job_ids: list[int], status: str = "queued") -> int:
    """Queue application submissions for a user (skips already existing)."""
    return stage_user_applications(user_id, [{"job_id": jid, "status": status} for jid in job_ids])


def list_fill_plan_candidates(user_ids: list[int], limit: int = 200) -> list[dict]:
    """Greenhouse To Apply rows of these users with no fill plan, or one older than a day (#129).

    `previous_plan` is the stored plan (or None), so a refresh can keep drafts already written (#59).
    """
    if not user_ids:
        return []
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.id, a.user_id, jp.external_id, jp.url, jp.title, c.ats_identifier, p.plan
            FROM applications a
            JOIN job_postings jp ON jp.id = a.job_posting_id
            JOIN companies c ON c.id = jp.company_id
            LEFT JOIN application_fill_plans p ON p.application_id = a.id
            WHERE a.user_id = ANY(%s)
              AND a.status = 'manual_apply'
              AND c.ats_platform = 'greenhouse'
              AND (p.application_id IS NULL OR p.built_at < NOW() - INTERVAL '1 day')
            ORDER BY p.built_at NULLS FIRST, a.id -- rows with no plan first, then the stalest, so none is starved
            LIMIT %s
            """,
            (user_ids, limit),
        )
        return [
            {
                "application_id": r[0],
                "user_id": r[1],
                "posting": {
                    "external_id": r[2],
                    "url": r[3],
                    "title": r[4],
                    "ats_identifier": r[5],
                    "ats_platform": "greenhouse",
                },
                "previous_plan": r[6] if isinstance(r[6], dict) or r[6] is None else json.loads(r[6]),
            }
            for r in cur.fetchall()
        ]


def upsert_fill_plan(application_id: int, plan: dict) -> None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO application_fill_plans (application_id, plan, built_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (application_id) DO UPDATE SET plan = EXCLUDED.plan, built_at = NOW()
            """,
            (application_id, json.dumps(plan)),
        )


def get_user_answers(user_ids: list[int]) -> dict[int, list[dict]]:
    """Saved questions of these users (answer memory), oldest first. Answers are never read here."""
    if not user_ids:
        return {}
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, user_id, question, question_key FROM user_answers WHERE user_id = ANY(%s) ORDER BY id",
            (user_ids,),
        )
        saved: dict[int, list[dict]] = {uid: [] for uid in user_ids}
        for r in cur.fetchall():
            saved.setdefault(r[1], []).append({"id": r[0], "question": r[2], "question_key": r[3]})
        return saved


def add_pending_questions(user_id: int, questions: list[dict]) -> list[dict]:
    """Add {question, question_key} rows with no answer; existing keys are skipped. Returns the rows added."""
    added: list[dict] = []
    if not questions:
        return added
    with get_connection() as conn, conn.cursor() as cur:
        for q in questions:
            cur.execute(
                """
                INSERT INTO user_answers (user_id, question, question_key) VALUES (%s, %s, %s)
                ON CONFLICT (user_id, question_key) DO NOTHING
                RETURNING id, question, question_key
                """,
                (user_id, q["question"][:500], q["question_key"]),
            )
            row = cur.fetchone()
            if row:
                added.append({"id": row[0], "question": row[1], "question_key": row[2]})
    return added


def expire_open_remote_sessions() -> int:
    """Kill switch (#129): every open remote apply session becomes expired."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE remote_apply_sessions SET status = 'expired', ended_at = NOW() WHERE status = 'open'")
        return cur.rowcount


def get_user_unnotified_matches(user_id: int) -> list[dict]:
    """Fetch unnotified matching job postings for a specific user."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT jp.id, jp.title, c.name AS company_name, jp.location, jp.url,
                   jp.compensation, jp.application_deadline, c.ats_platform, ujm.match_score
            FROM user_job_matches ujm
            JOIN job_postings jp ON jp.id = ujm.job_posting_id
            JOIN companies c ON c.id = jp.company_id
            WHERE ujm.user_id = %s AND ujm.notified_at IS NULL
            ORDER BY jp.first_seen_at DESC
            """,
            (user_id,),
        )
        cols = (
            "id",
            "title",
            "company_name",
            "location",
            "url",
            "compensation",
            "application_deadline",
            "ats_platform",
            "match_score",
        )
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def get_user_recent_application_activity(user_id: int) -> dict[str, list[dict]]:
    """Fetch recent applications grouped by status for personalized daily digest."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.id, jp.title, c.name AS company_name, a.submitted_payload, a.created_at
            FROM applications a
            JOIN job_postings jp ON jp.id = a.job_posting_id
            JOIN companies c ON c.id = jp.company_id
            WHERE a.user_id = %s AND a.status = 'submitted' AND a.created_at >= CURRENT_DATE
            ORDER BY a.created_at DESC
            """,
            (user_id,),
        )
        submitted = []
        for r in cur.fetchall():
            payload = r[3] if isinstance(r[3], dict) else (json.loads(r[3]) if r[3] else {})
            # Nothing is submitted for the user any more (#48), so a row without an employer ID was marked by them.
            confirmation = (payload or {}).get("confirmation_id") or "marked as applied by you"
            submitted.append(
                {
                    "application_id": r[0],
                    "title": r[1],
                    "company_name": r[2],
                    "confirmation": confirmation,
                    "created_at": r[4],
                }
            )

        cur.execute(
            """
            SELECT a.id, jp.title, c.name AS company_name, jp.url
            FROM applications a
            JOIN job_postings jp ON jp.id = a.job_posting_id
            JOIN companies c ON c.id = jp.company_id
            WHERE a.user_id = %s AND a.status = 'needs_review'
            ORDER BY a.created_at DESC
            """,
            (user_id,),
        )
        needs_review = [
            {"application_id": r[0], "title": r[1], "company_name": r[2], "url": r[3]} for r in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT a.id, jp.title, c.name AS company_name, jp.location, jp.url, jp.compensation
            FROM applications a
            JOIN job_postings jp ON jp.id = a.job_posting_id
            JOIN companies c ON c.id = jp.company_id
            WHERE a.user_id = %s AND a.status = 'manual_apply' AND a.created_at >= CURRENT_DATE
            ORDER BY a.created_at DESC
            """,
            (user_id,),
        )
        manual_apply = [
            {
                "application_id": r[0],
                "title": r[1],
                "company_name": r[2],
                "location": r[3],
                "url": r[4],
                "compensation": r[5],
            }
            for r in cur.fetchall()
        ]

        return {
            "submitted_today": submitted,
            "needs_review": needs_review,
            "manual_apply": manual_apply,
        }


def mark_user_matches_notified(user_id: int, job_ids: list[int]) -> int:
    """Mark specific job matches as notified for a user."""
    if not job_ids:
        return 0
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE user_job_matches
            SET notified_at = NOW()
            WHERE user_id = %s AND job_posting_id = ANY(%s)
            """,
            (user_id, job_ids),
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


def claim_next_queued_application(domain_throttle_seconds: int = 60) -> dict | None:
    """Atomically claim the next eligible queued application using SELECT ... FOR UPDATE OF a SKIP LOCKED.

    Enforces:
    - Confirmed CV: replacing it clears the confirmation, so applications already queued wait for a new review.
    - 60s domain throttle: Excludes applications whose company board had an active lock within domain_throttle_seconds.
    - User daily cap: Submissions today for user < user.max_daily_applications (default 10).
    - User per-company cap: Submissions for user at company < user.max_apps_per_company (default 2).

    Atomically updates status = 'submitting', attempt_token, locked_at = NOW(), and increments attempts.
    Logs 'queued' -> 'submitting' event in application_events.
    Commits and releases database connection immediately before returning.
    """
    attempt_token = str(uuid.uuid4())
    sql = """
        WITH candidate AS (
            SELECT a.id
            FROM applications a
            JOIN job_postings jp ON a.job_posting_id = jp.id
            JOIN companies c ON jp.company_id = c.id
            JOIN users u ON a.user_id = u.id
            WHERE a.status = 'queued'
              AND (a.next_attempt_at IS NULL OR a.next_attempt_at <= NOW())
              AND u.auto_apply_mode != 'disabled'
              AND u.resume_confirmed_at IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM applications active_apps
                  JOIN job_postings active_jp ON active_apps.job_posting_id = active_jp.id
                  WHERE active_jp.company_id = jp.company_id
                    AND active_apps.locked_at > NOW() - make_interval(secs => %(throttle_secs)s)
              )
              AND (
                  SELECT COUNT(*) FROM applications u_apps
                  WHERE u_apps.user_id = a.user_id
                    AND u_apps.status IN ('submitting', 'submitted')
                    AND u_apps.locked_at >= CURRENT_DATE
              ) < COALESCE(u.max_daily_applications, 10)
              AND (
                  SELECT COUNT(*) FROM applications uc_apps
                  JOIN job_postings uc_jp ON uc_apps.job_posting_id = uc_jp.id
                  WHERE uc_apps.user_id = a.user_id
                    AND uc_jp.company_id = jp.company_id
                    AND uc_apps.status IN ('submitting', 'submitted')
              ) < COALESCE(u.max_apps_per_company, 2)
            ORDER BY a.created_at ASC
            FOR UPDATE OF a SKIP LOCKED
            LIMIT 1
        ),
        updated AS (
            UPDATE applications a
            SET status = 'submitting',
                attempt_token = %(attempt_token)s::uuid,
                locked_at = NOW(),
                attempts = COALESCE(a.attempts, 0) + 1
            FROM candidate c_cand
            WHERE a.id = c_cand.id
            RETURNING a.id, a.user_id, a.job_posting_id, a.attempt_token, a.attempts
        )
        SELECT u_app.id, u_app.user_id, u_app.job_posting_id, jp.company_id, comp.name AS company_name,
               comp.ats_platform, comp.ats_identifier, jp.url AS job_url, jp.title AS job_title,
               u_app.attempt_token, u_app.attempts,
               usr.screening_defaults, usr.resume_data, usr.resume_storage_path, usr.resume_filename, usr.resume_content_type,
               usr.auth_user_id, usr.email
        FROM updated u_app
        JOIN job_postings jp ON u_app.job_posting_id = jp.id
        JOIN companies comp ON jp.company_id = comp.id
        JOIN users usr ON u_app.user_id = usr.id
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, {"throttle_secs": domain_throttle_seconds, "attempt_token": attempt_token})
        row = cur.fetchone()
        if not row:
            return None

        screening_defaults = (row[11] if isinstance(row[11], dict) else (json.loads(row[11]) if row[11] else {})) or {}
        resume_data = (row[12] if isinstance(row[12], dict) else (json.loads(row[12]) if row[12] else {})) or {}

        claim = {
            "id": row[0],
            "user_id": row[1],
            "job_posting_id": row[2],
            "company_id": row[3],
            "company_name": row[4],
            "ats_platform": row[5],
            "ats_identifier": row[6],
            "job_url": row[7],
            "job_title": row[8],
            "attempt_token": str(row[9]),
            "attempts": row[10],
            "screening_defaults": screening_defaults,
            "resume_data": resume_data,
            "resume_storage_path": row[13],
            "resume_filename": row[14],
            "resume_content_type": row[15],
            "auth_user_id": str(row[16]) if len(row) > 16 and row[16] is not None else None,
            "email": row[17] if len(row) > 17 else None,
        }

        cur.execute(
            """
            INSERT INTO application_events (application_id, from_status, to_status, reason)
            VALUES (%s, 'queued', 'submitting', 'claimed_by_worker')
            """,
            (claim["id"],),
        )
        return claim


def transition_application_status(
    application_id: int,
    to_status: str,
    from_status: str | None = None,
    reason: str | None = None,
    submitted_payload: dict | None = None,
    next_attempt_at: datetime | None = None,
) -> bool:
    """Update application status, optional payload and next attempt, and record an audit event.

    When ``from_status`` is given the update is a compare-and-set: it only applies if the row is still in
    that status, so a worker that outlived the stalled-application reaper cannot overwrite the reaper's state.
    Returns False (and writes no event) when nothing was updated.

    Commits and releases database connection immediately.
    """
    payload_json = json.dumps(submitted_payload) if submitted_payload is not None else None
    sql = """
        UPDATE applications
        SET status = %s,
            submitted_payload = COALESCE(%s::jsonb, submitted_payload),
            next_attempt_at = %s
        WHERE id = %s
    """
    params: tuple = (to_status, payload_json, next_attempt_at, application_id)
    if from_status is not None:
        sql += "  AND status = %s\n"
        params += (from_status,)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        if cur.rowcount == 0:
            if from_status is not None:
                logger.warning(
                    "Application %s not in status %r; skipped transition to %r", application_id, from_status, to_status
                )
            return False

        cur.execute(
            """
            INSERT INTO application_events (application_id, from_status, to_status, reason)
            VALUES (%s, %s, %s, %s)
            """,
            (application_id, from_status, to_status, reason),
        )
        return True


def reap_stalled_applications(stalled_threshold_seconds: int = 300) -> int:
    """Reap applications stuck in 'submitting' beyond threshold seconds.

    Transitions them to 'needs_review' with reason 'worker_timeout_unconfirmed'.
    Records corresponding application_events.
    Returns number of reaped applications.
    """
    sql = """
        WITH stalled AS (
            SELECT id
            FROM applications
            WHERE status = 'submitting'
              AND locked_at < NOW() - make_interval(secs => %s)
            FOR UPDATE SKIP LOCKED
        ),
        updated AS (
            UPDATE applications a
            SET status = 'needs_review'
            FROM stalled s
            WHERE a.id = s.id
            RETURNING a.id
        )
        INSERT INTO application_events (application_id, from_status, to_status, reason)
        SELECT id, 'submitting', 'needs_review', 'worker_timeout_unconfirmed'
        FROM updated
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(sql, (stalled_threshold_seconds,))
        return cur.rowcount
