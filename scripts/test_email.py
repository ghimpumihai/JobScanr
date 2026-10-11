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

from config import setup_logging  # noqa: E402

logger = logging.getLogger(__name__)


def fetch_sample(limit: int) -> list[dict]:
    from db import queries

    return queries.get_recent_job_samples(limit)


def main() -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="Preview digest email.")
    parser.add_argument("--limit", type=int, default=5, help="how many recent postings to include")
    parser.add_argument("--staging", action="store_true", help="use staging environment (.env.stage)")
    parser.add_argument("--personalized", action="store_true", help="preview personalized 4-section digest")
    args = parser.parse_args()

    import config

    config.load_environment(staging=args.staging)

    jobs = fetch_sample(args.limit)
    if not jobs:
        logger.warning("No rows to sample.")
        return 1

    from jobs.notify import send_email_digest, send_user_digest

    recipient = config.DIGEST_EMAIL
    logger.info("Previewing %d rows -> %s", len(jobs), recipient)

    if args.personalized:
        sample_user = {"email": recipient}
        sample_activity = {
            "submitted_today": [
                {"title": "Junior Software Engineer", "company_name": "Datadog", "confirmation": "APP-98214"}
            ],
            "needs_review": [
                {"title": "Backend Developer", "company_name": "Scale AI", "url": "https://scale.com/careers"}
            ],
            "manual_apply": [
                {
                    "title": "Software Engineer Intern",
                    "company_name": "Salesforce (Workday)",
                    "location": "London, UK",
                    "compensation": "£52,000",
                    "url": "https://salesforce.wd1.myworkdayjobs.com/careers",
                }
            ],
        }
        send_user_digest(sample_user, jobs, sample_activity)
    else:
        send_email_digest(jobs)

    logger.info("Preview digest sent (no DB writes).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
