"""Daily cycle entry point (plan Phase 5): scrape -> match -> store -> digest.

Usage:
  python -m jobs.scrape_and_notify             # normal daily run
  python -m jobs.scrape_and_notify --dry-run   # fetch + match, no DB writes, no email
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
        job["ats_platform"] = company["ats_platform"]
    return jobs


async def scrape_all(companies: list[dict]) -> tuple[list[dict], list[str]]:
    # Ashby soft-throttles concurrent bursts, so it gets its own slow lane.
    ashby_ids = {c["id"] for c in companies if c["ats_platform"] == "ashby"}
    async with make_http_client() as http:
        sem = asyncio.Semaphore(10)
        ashby_sem = asyncio.Semaphore(3)

        async def fetch(c):
            gate = ashby_sem if c["id"] in ashby_ids else sem
            async with gate:
                return await fetch_company(http, c)

        results = await asyncio.gather(
            *(fetch(c) for c in companies),
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
    parser.add_argument("--dry-run", action="store_true",
                        help="fetch + match, no DB writes, no email")
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

    # Ashby/SmartRecruiters-style listings ship without descriptions; fetch
    # details only for candidates passing the cheap title/location gate so
    # country-restriction and experience checks see full text.
    from jobs.enrich import enrich_jobs, passes_prefilter
    candidates = [j for j in jobs if passes_prefilter(j)]
    if candidates:
        async def _enrich():
            async with make_http_client() as http:
                return await enrich_jobs(candidates, http)
        asyncio.run(_enrich())
        print(f"Enriched {len(candidates)} description-less candidates.")

    # Filter BEFORE persisting: the DB is an archive of matches only.
    # Dedup (UNIQUE constraint + is_new) still suppresses re-notifications,
    # and failed sends stay unnotified for retry on the next run.
    matches = [j for j in jobs if matches_profile(j)]
    print(f"{len(matches)} jobs match profile:")
    for j in matches[:20]:
        print(f"  - {j['title']} @ {j['company_name']} ({j['location']})")

    if args.dry_run:
        print("[dry-run] no DB writes, no email.")
        return 0

    new_matches = queries.upsert_jobs(matches)
    stale = queries.delete_stale_jobs(days=3)
    print(f"Stored {len(new_matches)} new / {len(matches)} matched; pruned {stale} stale.")

    if not new_matches:
        print("Nothing to notify.")
        return 0

    from jobs.notify import email_configured, send_email_digest

    if not email_configured():
        # Leave notified_at NULL so the next configured run retries these.
        print("Matches found but no delivery channel — they will be retried.")
        return 1

    message_id = send_email_digest(new_matches)
    queries.mark_notified([j["id"] for j in new_matches])
    print(f"Email digest sent ({message_id}) for {len(new_matches)} jobs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
