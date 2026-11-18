"""Daily cycle entry point (plan Phase 5): scrape -> match -> store -> digest.

Usage:
  python -m jobs.scrape_and_notify             # normal daily run
  python -m jobs.scrape_and_notify --dry-run   # fetch + match, no DB writes, no email
  python -m jobs.scrape_and_notify --staging   # run against staging environment (.env.stage)
"""

import argparse
import asyncio
import collections
import hashlib
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone

from ats_identifiers import identifier_error
from config import setup_logging
from db import queries
from jobs.match import matches_profile
from models import Company, JobPosting
from scrapers import get_client
from scrapers.base import BlockedByChallenge, make_http_client
from scrapers.workday import WorkdayClient

logger = logging.getLogger(__name__)

FAILURE_RATE_LIMIT = 0.2
# A Workday job's detail page is re-fetched at most this often; in between, cached per-profile verdicts are reused.
ENRICH_TTL = timedelta(days=7)


async def fetch_company(
    http, company: Company | dict, state: dict | None = None, countries: set[str] | None = None
) -> list[JobPosting]:
    problem = identifier_error(company["ats_platform"], company["ats_identifier"])
    if problem:  # never interpolate an unchecked identifier into a request URL
        raise ValueError(f"invalid ats_identifier {company['ats_identifier']!r}: {problem}")
    client = get_client(company["ats_platform"], http)
    if isinstance(client, WorkdayClient):
        jobs = await client.get_jobs(company["ats_identifier"], state=state, countries=countries)
    else:
        jobs = await client.get_jobs(company["ats_identifier"])
    for job in jobs:
        job["company_id"] = company["id"]
        job["company_name"] = company["name"]
        job["ats_platform"] = company["ats_platform"]
    return jobs


PROGRESS_EVERY = 200


async def scrape_all(
    companies: list[Company | dict],
    failure_details: list[dict] | None = None,
    blocked: list[dict] | None = None,
    workday_states: dict[int, dict] | None = None,
    countries: set[str] | None = None,
) -> tuple[list[JobPosting], list[str]]:
    # Separate concurrency pools by platform characteristics:
    # - Fast platforms (Greenhouse, Lever, SmartRecruiters, Teamtailor): high throughput (30)
    # - Workday: dedicated concurrent pool (20) so multi-page crawls never starve fast platforms
    # - Ashby: independent serialized pacing lock (0.5s) to prevent 429s and soft-throttle drops
    async with make_http_client() as http:
        fast_sem = asyncio.Semaphore(30)
        workday_sem = asyncio.Semaphore(20)
        ashby_lock = asyncio.Lock()

        done = [0]
        # platform -> [finished, total request seconds, errors]; shows which platform is the slow one.
        stats: dict[str, list[float]] = {}
        totals = collections.Counter(c.get("ats_platform") for c in companies)

        async def fetch(c):
            try:
                return await _fetch(c)
            finally:
                done[0] += 1
                if done[0] % PROGRESS_EVERY == 0:
                    detail = ", ".join(
                        f"{p}={int(v[0])}/{totals[p]} avg={v[1] / max(v[0], 1):.1f}s err={int(v[2])}"
                        for p, v in sorted(stats.items())
                    )
                    logger.info("Scrape progress: %d/%d companies (%s)", done[0], len(companies), detail)

        async def timed(c):
            st = stats.setdefault(c.get("ats_platform"), [0, 0.0, 0])
            t0 = time.monotonic()
            try:
                if c.get("ats_platform") == "workday" and workday_states is not None:
                    return await fetch_company(http, c, workday_states.setdefault(c["id"], {}), countries)
                return await fetch_company(http, c)
            except Exception:
                st[2] += 1
                raise
            finally:
                st[0] += 1
                st[1] += time.monotonic() - t0

        async def _fetch(c):
            plat = c.get("ats_platform")
            if plat == "ashby":
                async with ashby_lock:
                    await asyncio.sleep(0.5)
                    return await timed(c)
            elif plat == "workday":
                async with workday_sem:
                    return await timed(c)
            else:
                async with fast_sem:
                    return await timed(c)

        results = await asyncio.gather(
            *(fetch(c) for c in companies),
            return_exceptions=True,
        )
    all_jobs: list[dict] = []
    failures: list[str] = []
    for company, result in zip(companies, results):
        if isinstance(result, BlockedByChallenge):
            # Turned away by a bot challenge: neither a scraper failure nor a dead board. Reported separately so
            # it cannot trip the failure-rate breaker or be "repaired" (pruned/rewritten) by the link fixer.
            if blocked is not None:
                blocked.append(company)
            if failure_details is not None:
                failure_details.append(
                    {
                        "company_id": company.get("id"),
                        "company_name": company.get("name"),
                        "ats_platform": company.get("ats_platform"),
                        "ats_identifier": company.get("ats_identifier"),
                        "career_url": company.get("career_url"),
                        "error": str(result),
                        "status_code": 429,
                        "blocked": True,
                    }
                )
            continue
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

    try:
        workday_states = queries.get_workday_board_states()
    except Exception as e:  # first run before the schema is applied, or a read failure: scan without the cache
        logger.warning("Could not load Workday board state, scanning without it: %s", e)
        workday_states = {}

    logger.info("Scraping %d companies...", len(companies))
    failure_details: list[dict] = []
    blocked: list[dict] = []
    WorkdayClient.requests_sent = 0
    jobs, failures = await scrape_all(
        companies,
        failure_details=failure_details,
        blocked=blocked,
        workday_states=workday_states,
        countries=_facet_countries(active_users, profile),
    )
    logger.info("Workday list requests sent: %d.", WorkdayClient.requests_sent)
    if blocked:
        by_platform = collections.Counter(c.get("ats_platform") for c in blocked)
        logger.warning(
            "%d of %d companies were not scraped today because the host answered with a Cloudflare challenge, %s. "
            "They are skipped (not failures) and retried on the next run.",
            len(blocked),
            len(companies),
            ", ".join(f"{p}={n}" for p, n in sorted(by_platform.items())),
        )

    if failures:
        logger.info("Scrape finished with %d failures across %d companies.", len(failures), len(companies))
        for failure in failures:
            logger.debug("FAIL %s", failure)

    if args.failures_file and failure_details:
        import json
        from pathlib import Path

        Path(args.failures_file).write_text(json.dumps(failure_details, indent=2))
        logger.info("Wrote %d failure details to %s.", len(failure_details), args.failures_file)

    attempted = len(companies) - len(blocked)
    if attempted > 0 and len(failures) > attempted * FAILURE_RATE_LIMIT:
        logger.error("Failure rate too high — aborting.")
        return 1

    logger.info("Fetched %d live job postings.", len(jobs))

    # Ashby/SmartRecruiters-style listings ship without descriptions; fetch
    # details only for candidates passing the union prefilter across active users.
    from jobs.enrich import enrich_jobs, extract_compensation, passes_prefilter_multiuser

    hashes = {id(u): _profile_hash(u.get("profile_filters") or profile) for u in active_users}
    candidates = [j for j in jobs if passes_prefilter_multiuser(j, active_users)]
    candidates = [j for j in candidates if not _apply_cached_enrichment(j, workday_states, set(hashes.values()))]
    if candidates:
        # Detail endpoints throttle hardest right after a full scrape;
        # let the window cool before enriching.
        await asyncio.sleep(15)

        before = WorkdayClient.requests_sent
        async with make_http_client() as http:
            await enrich_jobs(candidates, http)
        logger.info("Enriched %d description-less candidates.", len(candidates))
        logger.info("Workday detail requests sent: %d.", WorkdayClient.requests_sent - before)

    # Extract compensation for any postings containing description text
    for j in jobs:
        if j.get("description") and not j.get("compensation"):
            j["compensation"] = extract_compensation(j.get("description"))

    # Evaluate matches per active user and collect unique matched jobs to store
    user_match_map: dict[int | None, list[dict]] = {}
    all_matched_jobs_map: dict[tuple[str, int | None], dict] = {}

    for u in active_users:
        u_filters = u.get("profile_filters") or profile
        u_matches = [j for j in jobs if _match(j, u_filters, hashes[id(u)])]
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
        logger.info("[dry-run] Workday board state not saved (%d boards).", len(workday_states))
        for u in active_users:
            u_matches = user_match_map.get(u.get("id"), [])
            logger.info("[dry-run] User %s matches %d job(s).", u.get("email"), len(u_matches))
        logger.info("[dry-run] no DB writes, no email.")
        return 0

    _record_enrichment(jobs, workday_states)
    try:
        queries.save_workday_board_states(workday_states)
    except Exception as e:  # a lost cache only costs requests next run; never block the digest on it
        logger.warning("Could not save Workday board state: %s", e)
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


def _facet_countries(active_users: list[dict], profile: dict) -> set[str] | None:
    """Lowercase country names to narrow large Workday boards with, or None to not narrow.

    Built from every user's locations plus eligible_regions (non-country entries simply match no facet).
    A user without eligible_regions may have city-only locations whose country we can't infer, so then
    nothing is narrowed. Narrowing drops postings in other countries, "Remote - <other country>" included.
    """
    out: set[str] = set()
    for u in active_users:
        f = u.get("profile_filters") or profile
        if not f.get("eligible_regions"):
            return None
        out |= {str(x).strip().lower() for x in [*f["eligible_regions"], *(f.get("locations") or [])]}
    return out or None


def _profile_hash(filters: dict) -> str:
    return hashlib.sha256(json.dumps(filters, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _apply_cached_enrichment(job: dict, states: dict[int, dict], hashes: set[str]) -> bool:
    """Reuse a recent Workday detail fetch instead of repeating it. True if the job needs no fetch.

    Only the enrichment fields and a yes/no verdict per profile are cached (never the description), so a
    cache hit requires a verdict for every active profile; a new or edited profile forces a fresh fetch.
    """
    if job.get("ats_platform") != "workday":
        return False
    entry = (states.get(job["company_id"]) or {}).get("enrichment", {}).get(job["external_id"])
    if not entry or datetime.now(timezone.utc) - datetime.fromisoformat(entry["at"]) >= ENRICH_TTL:
        return False
    if not hashes <= entry.get("verdicts", {}).keys():
        return False
    for k in ("location", "url", "compensation", "application_deadline"):
        if entry.get(k):
            job[k] = entry[k]
    job["_verdicts"] = entry["verdicts"]
    return True


def _match(job: dict, filters: dict, profile_hash: str) -> bool:
    verdicts = job.get("_verdicts")
    if verdicts is not None and profile_hash in verdicts:
        return verdicts[profile_hash]
    verdict = matches_profile(job, filters)
    # Only a verdict made with the full description is worth caching; a failed fetch would cache a looser one.
    if job.get("ats_platform") == "workday" and job.get("description"):
        job.setdefault("_new_verdicts", {})[profile_hash] = verdict
    return verdict


def _record_enrichment(jobs: list[dict], states: dict[int, dict]) -> None:
    """Store today's fresh verdicts and drop cache entries for jobs no longer listed."""
    now = datetime.now(timezone.utc).isoformat()
    listed: dict[int, set[str]] = collections.defaultdict(set)
    for j in jobs:
        if j.get("ats_platform") != "workday":
            continue
        listed[j["company_id"]].add(j["external_id"])
        state = states.get(j["company_id"])
        if state is None or not j.get("_new_verdicts"):
            continue
        state.setdefault("enrichment", {})[j["external_id"]] = {
            "at": now,
            "verdicts": j["_new_verdicts"],
            **{k: j.get(k) for k in ("location", "url", "compensation", "application_deadline")},
        }
    for cid, state in states.items():
        if cid in listed:
            state["enrichment"] = {k: v for k, v in (state.get("enrichment") or {}).items() if k in listed[cid]}


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
