"""Daily cycle entry point (plan Phase 5): scrape -> match -> store -> digest.

Usage:
  python -m jobs.scrape_and_notify             # normal daily run
  python -m jobs.scrape_and_notify --dry-run   # fetch + match, no DB writes, no email
  python -m jobs.scrape_and_notify --staging   # run against staging environment (.env.stage)
"""

import argparse
import asyncio
import logging
import sys

from config import PROFILE, setup_logging
from db import queries
from jobs.match import matches_profile
from models import Company, JobPosting
from scrapers import get_client
from scrapers.base import make_http_client

logger = logging.getLogger(__name__)

FAILURE_RATE_LIMIT = 0.2


async def fetch_company(http, company: Company | dict) -> list[JobPosting]:
    client = get_client(company["ats_platform"], http)
    jobs = await client.get_jobs(company["ats_identifier"])
    for job in jobs:
        job["company_id"] = company["id"]
        job["company_name"] = company["name"]
        job["ats_platform"] = company["ats_platform"]
    return jobs


async def scrape_all(companies: list[Company | dict],
                       failure_details: list[dict] | None = None) -> tuple[list[JobPosting], list[str]]:
    # Ashby throttles concurrent bursts, so it gets a dedicated paced lane.
    ashby_ids = {c["id"] for c in companies if c["ats_platform"] == "ashby"}
    async with make_http_client() as http:
        sem = asyncio.Semaphore(10)
        ashby_lock = asyncio.Lock()

        async def fetch(c):
            if c["id"] in ashby_ids:
                async with ashby_lock:
                    await asyncio.sleep(0.5)
                async with sem:
                    return await fetch_company(http, c)
            else:
                async with sem:
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
            if failure_details is not None:
                resp = getattr(result, "response", None)
                status_code = getattr(resp, "status_code", None)
                failure_details.append({
                    "company_id": company.get("id"),
                    "company_name": company.get("name"),
                    "ats_platform": company.get("ats_platform"),
                    "ats_identifier": company.get("ats_identifier"),
                    "career_url": company.get("career_url"),
                    "error": str(result),
                    "status_code": status_code,
                })
        else:
            all_jobs.extend(result)
    return all_jobs, failures


async def run_pipeline(args) -> int:
    import config
    profile = config.load_profile(args.profile) if getattr(args, "profile", None) else config.PROFILE
    companies = queries.get_all_companies()
    logger.info("Scraping %d companies...", len(companies))
    failure_details: list[dict] = []
    jobs, failures = await scrape_all(companies, failure_details=failure_details)

    for failure in failures:
        logger.warning("FAIL %s", failure)

    if args.failures_file and failure_details:
        import json
        from pathlib import Path
        Path(args.failures_file).write_text(json.dumps(failure_details, indent=2))
        logger.info("Wrote %d failure details to %s.", len(failure_details), args.failures_file)

    if len(failures) > len(companies) * FAILURE_RATE_LIMIT:
        logger.error("Failure rate too high — aborting.")
        return 1

    logger.info("Fetched %d live job postings.", len(jobs))

    # Ashby/SmartRecruiters-style listings ship without descriptions; fetch
    # details only for candidates passing the cheap title/location gate so
    # country-restriction and experience checks see full text.
    from jobs.enrich import enrich_jobs, passes_prefilter
    candidates = [j for j in jobs if passes_prefilter(j, profile)]
    if candidates:
        # Detail endpoints throttle hardest right after a full scrape;
        # let the window cool before enriching.
        await asyncio.sleep(15)

        async with make_http_client() as http:
            await enrich_jobs(candidates, http)
        logger.info("Enriched %d description-less candidates.", len(candidates))

    # Filter BEFORE persisting: the DB is an archive of matches only.
    # Dedup (UNIQUE constraint + is_new) still suppresses re-notifications,
    # and failed sends stay unnotified for retry on the next run.
    matches = [j for j in jobs if matches_profile(j, profile)]

    # Employers rarely fill structured salary fields but often paste ranges
    # into descriptions — extract for anything missing one.
    from jobs.enrich import extract_compensation
    for j in matches:
        if not j.get("compensation"):
            j["compensation"] = extract_compensation(j.get("description"))
    logger.info("%d jobs match profile:", len(matches))
    for j in matches[:20]:
        logger.info("  - %s @ %s (%s)", j['title'], j['company_name'], j['location'])

    if args.dry_run:
        logger.info("[dry-run] no DB writes, no email.")
        return 0

    new_matches = queries.upsert_jobs(matches)
    stale = queries.delete_stale_jobs(days=30)
    logger.info("Stored %d new / %d matched; pruned %d stale.", len(new_matches), len(matches), stale)

    if not new_matches:
        logger.info("Nothing to notify.")
        return 0

    from jobs.notify import email_configured, send_email_digest

    if not email_configured():
        # Leave notified_at NULL so the next configured run retries these.
        logger.warning("Matches found but no delivery channel — they will be retried.")
        return 1

    message_id = send_email_digest(new_matches)
    queries.mark_notified([j["id"] for j in new_matches])
    logger.info("Email digest sent (%s) for %d jobs.", message_id, len(new_matches))
    return 0


def main() -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="JobScanr scrape & digest runner.")
    parser.add_argument("--dry-run", action="store_true",
                        help="fetch + match, no DB writes, no email")
    parser.add_argument("--staging", action="store_true",
                        help="use staging environment (.env.stage)")
    parser.add_argument("--failures-file", type=str, default=None,
                        help="path to write structured failures JSON")
    parser.add_argument("--profile", type=str, default=None,
                        help="path to custom profile JSON")
    args = parser.parse_args()

    return asyncio.run(run_pipeline(args))


if __name__ == "__main__":
    sys.exit(main())
