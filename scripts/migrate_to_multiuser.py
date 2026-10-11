"""Migrate single-user profile.json to multi-user database schema as User 1.

Usage:
    python -m scripts.migrate_to_multiuser           # migrate in production
    python -m scripts.migrate_to_multiuser --staging # migrate in staging
    python -m scripts.migrate_to_multiuser --dry-run # dry-run inspection
"""

import argparse
import json
import logging
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from db import queries

logger = logging.getLogger(__name__)

DEFAULT_MIGRATION_UUID = "00000000-0000-0000-0000-000000000001"


def get_default_screening() -> dict:
    return {
        "work_authorization": True,
        "requires_sponsorship": False,
        "years_experience": 1,
        "notice_period_days": 30,
    }


def migrate_profile_to_user(
    profile_data: dict,
    email: str | None = None,
    auth_user_id: str | None = None,
    dry_run: bool = False,
) -> dict:
    raw_email = email or getattr(config, "DIGEST_EMAIL", "")
    if raw_email and "," in raw_email:
        user_email = raw_email.split(",")[0].strip()
    else:
        user_email = (raw_email or "user1@jobscanr.local").strip()
    uid = (auth_user_id or os.environ.get("MIGRATION_AUTH_USER_ID") or DEFAULT_MIGRATION_UUID).strip()
    try:
        uuid.UUID(uid)
    except ValueError:
        raise ValueError(f"Invalid UUID for auth_user_id: {uid}")

    screening_defaults = get_default_screening()
    resume_data: dict = {}

    user_payload = {
        "auth_user_id": uid,
        "email": user_email,
        "resume_data": resume_data,
        "profile_filters": profile_data,
        "screening_defaults": screening_defaults,
        "auto_apply_mode": "approval_required",
        "max_daily_applications": 10,
        "max_apps_per_company": 2,
    }

    if dry_run:
        logger.info("[DRY-RUN] Prepared User 1 payload: email=%s, auth_user_id=%s", user_email, uid)
        return {**user_payload, "id": 1}

    # Ensure schema is applied and auth.users has the stub record if needed
    with queries.get_connection() as conn, conn.cursor() as cur:
        # If auth.users exists, ensure the auth record exists so FK constraint succeeds
        try:
            cur.execute("SAVEPOINT auth_user_savepoint")
            cur.execute(
                """
                INSERT INTO auth.users (id, email)
                VALUES (%s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (uid, user_email),
            )
            cur.execute("RELEASE SAVEPOINT auth_user_savepoint")
        except Exception as e:
            try:
                cur.execute("ROLLBACK TO SAVEPOINT auth_user_savepoint")
            except Exception:
                pass
            logger.debug("auth.users insert skipped or unneeded: %s", e)

        cur.execute(
            """
            INSERT INTO users (
                auth_user_id, email, resume_data, profile_filters, screening_defaults,
                auto_apply_mode, max_daily_applications, max_apps_per_company, gdpr_consent_at
            )
            VALUES (
                %(auth_user_id)s, %(email)s, %(resume_data)s::jsonb, %(profile_filters)s::jsonb,
                %(screening_defaults)s::jsonb, %(auto_apply_mode)s, %(max_daily_applications)s,
                %(max_apps_per_company)s, NOW()
            )
            ON CONFLICT (email) DO UPDATE
                SET profile_filters = EXCLUDED.profile_filters,
                    screening_defaults = EXCLUDED.screening_defaults,
                    resume_data = EXCLUDED.resume_data
            RETURNING id, auth_user_id, email
            """,
            {
                **user_payload,
                "resume_data": json.dumps(resume_data),
                "profile_filters": json.dumps(profile_data),
                "screening_defaults": json.dumps(screening_defaults),
            },
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError("Failed to insert or update user record.")
        user_id, ret_uid, ret_email = row[0], str(row[1]), row[2]
        logger.info("Migrated User (id=%s, email=%s, auth_user_id=%s).", user_id, ret_email, ret_uid)
        return {**user_payload, "id": user_id, "auth_user_id": ret_uid, "email": ret_email}


def main() -> int:
    config.setup_logging()
    parser = argparse.ArgumentParser(description="Migrate single-user profile.json to multi-user DB schema.")
    parser.add_argument("--staging", action="store_true", help="use staging environment (.env.stage)")
    parser.add_argument("--dry-run", action="store_true", help="show planned migration without DB writes")
    parser.add_argument("--profile", type=str, default=None, help="path to custom profile JSON")
    parser.add_argument("--email", type=str, default=None, help="override email for User 1")
    parser.add_argument("--auth-user-id", type=str, default=None, help="override Supabase auth user UUID")
    args = parser.parse_args()

    config.load_environment(staging=args.staging)
    profile_data = config.load_profile(args.profile) if args.profile else config.PROFILE

    try:
        if not args.dry_run:
            logger.info("Applying database schema to %s environment...", config.DB_ENV)
            queries.apply_schema()
        migrate_profile_to_user(
            profile_data=profile_data,
            email=args.email,
            auth_user_id=args.auth_user_id,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        logger.error("Migration failed: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
