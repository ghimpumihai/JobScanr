"""Send a preview digest built from rows already in the database.

Purely read-only: selects recent postings and emails them. Never inserts,
updates, or deletes anything.

Usage:
  python -m scripts.test_email --staging --limit 3   # safe preview in staging
  python -m scripts.test_email                       # production rows
"""

import argparse
import sys

sys.path.insert(0, ".")

from config import DIGEST_EMAIL  # noqa: E402


def fetch_sample(limit: int) -> list[dict]:
    from db import queries

    with queries.get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT jp.title, c.name AS company_name, jp.location, jp.url
               FROM job_postings jp JOIN companies c ON c.id = jp.company_id
               ORDER BY jp.first_seen_at DESC
               LIMIT %s""",
            (limit,),
        )
        return [dict(zip(("title", "company_name", "location", "url"), r))
                for r in cur.fetchall()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview digest email.")
    parser.add_argument("--limit", type=int, default=5,
                        help="how many recent postings to include")
    parser.add_argument("--env", "-e", type=str, default=None,
                        help="environment name or file (e.g. stage, prod, .env.stage)")
    parser.add_argument("--env-file", type=str, default=None,
                        help="path to custom .env file")
    args = parser.parse_args()

    jobs = fetch_sample(args.limit)
    if not jobs:
        print("No rows to sample.")
        return 1

    print(f"Previewing {len(jobs)} rows -> {DIGEST_EMAIL}")
    from jobs.notify import send_email_digest

    send_email_digest(jobs)
    print("Preview digest sent (no DB writes).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
