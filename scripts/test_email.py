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
    parser.add_argument("--personalized", action="store_true", help="preview personalized digest")
    parser.add_argument("--heartbeat", action="store_true", help="preview zero-match heartbeat telemetry email")
    parser.add_argument("--save-html", type=str, default="", help="save rendered HTML to a file instead of sending")
    parser.add_argument("--simulate-volume", type=int, default=0, help="simulate N jobs to preview high-volume bridge")
    args = parser.parse_args()

    import config

    config.load_environment(staging=args.staging)

    from jobs.notify import build_html_digest, build_personalized_html_digest, send_email_digest, send_user_digest

    recipient = config.DIGEST_EMAIL or "stefan@example.com"
    sample_user = {"email": recipient}

    if args.heartbeat:
        jobs = []
    elif args.simulate_volume > 0:
        # Generate N synthetic jobs for high-volume preview
        companies = ["Revolut", "Spotify", "Datadog", "Cloudflare", "Amazon", "Monzo", "Wise", "Scale AI"]
        jobs = [
            {
                "title": f"Software Engineer Role {i + 1}",
                "company_name": companies[i % len(companies)],
                "location": "London, UK" if i % 2 == 0 else "Paris, France",
                "compensation": "€55,000 – €65,000 / yr",
                "ats_platform": "greenhouse" if i % 2 == 0 else "lever",
                "url": "https://example.com/job",
            }
            for i in range(args.simulate_volume)
        ]
    else:
        jobs = fetch_sample(args.limit)
        if not jobs:
            logger.warning("No rows to sample.")
            return 1

    logger.info("Previewing %d rows -> %s", len(jobs), recipient)

    if args.save_html:
        if args.personalized or args.heartbeat or args.simulate_volume:
            html_body = build_personalized_html_digest(sample_user, jobs)
        else:
            html_body = build_html_digest(jobs)

        wrapper = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>JobScanr Digest Preview</title>
</head>
<body style="margin:0;padding:24px 12px;background-color:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  {html_body}
</body>
</html>"""
        with open(args.save_html, "w", encoding="utf-8") as f:
            f.write(wrapper)
        logger.info("Saved preview HTML to %s", args.save_html)
        return 0

    if args.personalized or args.heartbeat or args.simulate_volume:
        send_user_digest(sample_user, jobs, send_heartbeat=args.heartbeat)
    else:
        send_email_digest(jobs)

    logger.info("Preview digest sent (no DB writes).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
