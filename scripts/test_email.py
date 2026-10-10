"""Send a preview digest built from rows already in the database.

Purely read-only: selects recent postings and emails them. Never inserts,
updates, or deletes anything.

Usage:
  python -m scripts.test_email --staging --limit 3   # safe preview in staging
  python -m scripts.test_email                       # production rows
"""

import argparse
import logging
import sys

sys.path.insert(0, ".")

from config import DIGEST_EMAIL, setup_logging  # noqa: E402

logger = logging.getLogger(__name__)


def fetch_sample(limit: int) -> list[dict]:
    from db import queries

    return queries.get_recent_job_samples(limit)


def main() -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="Preview digest email.")
    parser.add_argument("--limit", type=int, default=5,
                        help="how many recent postings to include")
    parser.add_argument("--staging", action="store_true",
                        help="use staging environment (.env.stage)")
    args = parser.parse_args()

    jobs = fetch_sample(args.limit)
    if not jobs:
        logger.warning("No rows to sample.")
        return 1

    logger.info("Previewing %d rows -> %s", len(jobs), DIGEST_EMAIL)
    from jobs.notify import send_email_digest

    send_email_digest(jobs)
    logger.info("Preview digest sent (no DB writes).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
