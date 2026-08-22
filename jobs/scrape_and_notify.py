"""Daily cycle entry point (plan Phase 5): scrape -> upsert -> match -> digest.

Usage:
  python -m jobs.scrape_and_notify             # normal daily run
  python -m jobs.scrape_and_notify --baseline  # insert current jobs, notify nobody
  python -m jobs.scrape_and_notify --dry-run   # fetch + match, no DB writes, no push
"""

import argparse
import asyncio
import sys

from config import PROFILE
from db import queries
from jobs.match import matches_profile
from scrapers import get_client
from scrapers.base import make_http_client

FAILURE_RATE_LIMIT = 0.2


async def fetch_company(http, company: dict) -> list[dict]:
    client = get_client(company["ats_platform"], http)
    jobs = await client.get_jobs(company["ats_identifier"])
    for job in jobs:
        job["company_id"] = company["id"]
        job["company_name"] = company["name"]
    return jobs


async def scrape_all(companies: list[dict]) -> tuple[list[dict], list[str]]:
    async with make_http_client() as http:
        results = await asyncio.gather(
            *(fetch_company(http, c) for c in companies),
            return_exceptions=True,
        )
    all_jobs: list[dict] = []
    failures: list[str] = []
    for company, result in zip(companies, results):
        if isinstance(result, Exception):
            failures.append(f"{company['name']} ({company['ats_platform']}): {result}")
        else:
            all_jobs.extend(result)
    return all_jobs, failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", action="store_true",
                        help="insert everything but send no notifications")
    parser.add_argument("--dry-run", action="store_true",
                        help="no DB writes, no push")
    args = parser.parse_args()

    companies = queries.get_all_companies()
    print(f"Scraping {len(companies)} companies...")
    jobs, failures = asyncio.run(scrape_all(companies))

    for failure in failures:
        print(f"  FAIL {failure}")
    if len(failures) > len(companies) * FAILURE_RATE_LIMIT:
        print("Failure rate too high — aborting.")
        return 1

    print(f"Fetched {len(jobs)} live job postings.")

    if args.dry_run:
        matches = [j for j in jobs if matches_profile(j)]
        print(f"[dry-run] would upsert {len(jobs)}; {len(matches)} match profile:")
        for j in matches[:15]:
            print(f"  - {j['title']} @ {j['company_name']} ({j['location']})")
        return 0

    new_jobs = queries.upsert_jobs(jobs)
    stale = queries.delete_stale_jobs(days=3)
    print(f"Upserted: {len(new_jobs)} new / {len(jobs)} live; pruned {stale} stale.")

    matches = [j for j in new_jobs if matches_profile(j)]
    print(f"{len(matches)} new jobs match profile:")
    for j in matches[:20]:
        print(f"  - {j['title']} @ {j['company_name']} ({j['location']})")

    if args.baseline:
        # First run: record everything as already-seen so tomorrow's first
        # real digest only contains genuinely fresh postings.
        queries.mark_notified([j["id"] for j in new_jobs])
        print("Baseline run: marked all as notified, sent nothing.")
        return 0

    if not matches:
        print("Nothing to notify.")
        return 0

    from jobs.notify import email_configured, send_digest, send_email_digest

    fcm_id = send_digest(matches)
    queries.mark_notified([j["id"] for j in matches])
    print(f"FCM digest sent ({fcm_id}) for {len(matches)} jobs.")
    if email_configured():
        message_id = send_email_digest(matches)
        print(f"Email digest sent ({message_id}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
