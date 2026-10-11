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

from config import setup_logging
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


async def scrape_all(
    companies: list[Company | dict], failure_details: list[dict] | None = None
) -> tuple[list[JobPosting], list[str]]:
    # Separate concurrency pools by platform characteristics:
    # - Fast platforms (Greenhouse, Lever, SmartRecruiters, Teamtailor): high throughput (30)
    # - Workday: dedicated concurrent pool (20) so multi-page crawls never starve fast platforms
    # - Ashby: independent serialized pacing lock (0.5s) to prevent 429s and soft-throttle drops
    async with make_http_client() as http:
        fast_sem = asyncio.Semaphore(30)
        workday_sem = asyncio.Semaphore(20)
        ashby_lock = asyncio.Lock()

        async def fetch(c):
            plat = c.get("ats_platform")
            if plat == "ashby":
                async with ashby_lock:
                    await asyncio.sleep(0.5)
                    return await fetch_company(http, c)
            elif plat == "workday":
                async with workday_sem:
                    return await fetch_company(http, c)
            else:
                async with fast_sem:
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
                failure_details.append(
                    {
                        "company_id": company.get("id"),
                        "company_name": company.get("name"),
                        "ats_platform": company.get("ats_platform"),
                        "ats_identifier": company.get("ats_identifier"),
                        "career_url": company.get("career_url"),
                        "error": str(result),
                        "status_code": status_code,
                    }
                )
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

    if failures:
        logger.info("Scrape finished with %d failures across %d companies.", len(failures), len(companies))
        for failure in failures:
            logger.debug("FAIL %s", failure)

    if args.failures_file and failure_details:
        import json
        from pathlib import Path

        Path(args.failures_file).write_text(json.dumps(failure_details, indent=2))
        logger.info("Wrote %d failure details to %s.", len(failure_details), args.failures_file)

    if len(failures) > len(companies) * FAILURE_RATE_LIMIT:
        logger.error("Failure rate too high — aborting.")
        return 1

    logger.info("Fetched %d live job postings.", len(jobs))

    active_users: list[dict] = []
    if not getattr(args, "profile", None):
        try:
            active_users = queries.get_active_users()
        except Exception as e:
            logger.debug("Could not fetch active users from DB, falling back to profile.json: %s", e)

    if not active_users:
        active_users = [
            {
                "id": None,
                "email": config.DIGEST_EMAIL,
                "profile_filters": profile,
                "auto_apply_mode": "disabled",
            }
        ]

    # Ashby/SmartRecruiters-style listings ship without descriptions; fetch
    # details only for candidates passing the union prefilter across active users.
    from jobs.enrich import enrich_jobs, extract_compensation, passes_prefilter_multiuser

    candidates = [j for j in jobs if passes_prefilter_multiuser(j, active_users)]
    if candidates:
        # Detail endpoints throttle hardest right after a full scrape;
        # let the window cool before enriching.
        await asyncio.sleep(15)

        async with make_http_client() as http:
            await enrich_jobs(candidates, http)
        logger.info("Enriched %d description-less candidates.", len(candidates))

    # Extract compensation for any postings containing description text
    for j in jobs:
        if j.get("description") and not j.get("compensation"):
            j["compensation"] = extract_compensation(j.get("description"))

    # Evaluate matches per active user and collect unique matched jobs to store
    user_match_map: dict[int | None, list[dict]] = {}
    all_matched_jobs_map: dict[tuple[str, int | None], dict] = {}

    for u in active_users:
        u_filters = u.get("profile_filters") or profile
        u_matches = [j for j in jobs if matches_profile(j, u_filters)]
        u_key = u.get("id")
        user_match_map[u_key] = u_matches
        for j in u_matches:
            k = (j["external_id"], j.get("company_id"))
            all_matched_jobs_map[k] = j

    all_matched_jobs = list(all_matched_jobs_map.values())
    logger.info(
        "Found %d unique job posting(s) matching across %d active user(s).",
        len(all_matched_jobs),
        len(active_users),
    )

    if args.dry_run:
        for u in active_users:
            u_matches = user_match_map.get(u.get("id"), [])
            logger.info("[dry-run] User %s matches %d job(s).", u.get("email"), len(u_matches))
        logger.info("[dry-run] no DB writes, no email.")
        return 0

    new_jobs = queries.upsert_jobs(all_matched_jobs)
    stale = queries.delete_stale_jobs(days=30)
    logger.info("Stored %d new / %d total matched; pruned %d stale.", len(new_jobs), len(all_matched_jobs), stale)

    # Build lookup by (external_id, company_id) to resolve database IDs
    job_id_lookup: dict[tuple[str, int | None], int] = {}
    for j in all_matched_jobs:
        if j.get("id"):
            job_id_lookup[(j["external_id"], j.get("company_id"))] = j["id"]

    # Record user matches and stage applications
    for u in active_users:
        uid = u.get("id")
        if not uid:
            continue
        u_matches = user_match_map.get(uid, [])
        match_records = []
        app_stage_items = []
        auto_mode = u.get("auto_apply_mode", "disabled")

        for j in u_matches:
            jid = j.get("id") or job_id_lookup.get((j["external_id"], j.get("company_id")))
            if not jid:
                continue
            match_records.append({"job_posting_id": jid, "match_score": 1.0})

            if auto_mode != "disabled":
                plat = (j.get("ats_platform") or "").lower()
                if plat in ("greenhouse", "lever"):
                    status = "queued" if auto_mode == "auto_submit" else "pending_approval"
                else:
                    status = "manual_apply"
                app_stage_items.append({"job_posting_id": jid, "status": status})

        if match_records:
            queries.upsert_user_matches(uid, match_records)
        if app_stage_items:
            queries.stage_user_applications(uid, app_stage_items)

    from jobs.notify import email_configured, send_email_digest, send_user_digest

    if not email_configured():
        logger.warning("Matches found but no delivery channel — they will be retried.")
        return 1

    sent_count = 0
    for u in active_users:
        uid = u.get("id")
        if uid:
            unnotified = queries.get_user_unnotified_matches(uid)
            activity = queries.get_user_recent_application_activity(uid)
            msg_id = send_user_digest(u, unnotified, activity)
            if msg_id:
                sent_count += 1
                if unnotified:
                    queries.mark_user_matches_notified(uid, [j["id"] for j in unnotified])
                logger.info("Personalized digest sent to %s (%d new matches).", u.get("email"), len(unnotified))
        else:
            if new_jobs:
                send_email_digest(new_jobs)
                queries.mark_notified([j["id"] for j in new_jobs])
                sent_count += 1
                logger.info("Email digest sent for %d jobs.", len(new_jobs))

    logger.info("Notification stage finished. Digests sent: %d.", sent_count)
    return 0


def main() -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="JobScanr scrape & digest runner.")
    parser.add_argument("--dry-run", action="store_true", help="fetch + match, no DB writes, no email")
    parser.add_argument("--staging", action="store_true", help="use staging environment (.env.stage)")
    parser.add_argument("--failures-file", type=str, default=None, help="path to write structured failures JSON")
    parser.add_argument("--profile", type=str, default=None, help="path to custom profile JSON")
    args = parser.parse_args()

    return asyncio.run(run_pipeline(args))


if __name__ == "__main__":
    sys.exit(main())
