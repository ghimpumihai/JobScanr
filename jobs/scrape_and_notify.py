"""Daily cycle entry point (plan Phase 5): scrape -> match -> store -> digest.

Usage:
  python -m jobs.scrape_and_notify             # normal daily run
  python -m jobs.scrape_and_notify --dry-run   # fetch + match, no DB writes, no email
  python -m jobs.scrape_and_notify --staging   # run against staging environment (.env.stage)
  python -m jobs.scrape_and_notify --platforms workday --no-email   # Workday-only scan, digest sent later
  python -m jobs.scrape_and_notify --skip-platforms workday         # daily digest without Workday requests
"""

import argparse
import asyncio
import collections
import hashlib
import json
import logging
import random
import sys
import time
from datetime import datetime, timedelta, timezone

from ats_identifiers import identifier_error
from config import setup_logging
from db import queries
from jobs.match import matches_profile
from models import Company, JobPosting
from scrapers import get_client
from scrapers.base import BlockedByChallenge, challenge_tracker, make_http_client
from scrapers.workday import WorkdayClient, full_scan_due, is_hot

logger = logging.getLogger(__name__)

FAILURE_RATE_LIMIT = 0.2
# Per-company cap so one hung board can't stall the run. Not applied to Workday: its boards queue for per-pod
# pacing slots (minutes on a big pod), and each of its requests already has its own timeout.
PER_COMPANY_TIMEOUT = 120.0
# Below this many attempted (not challenge-blocked) companies, the failure rate says nothing: 1 failure out of 2
# would abort a run in which Workday blocked everything else.
MIN_ATTEMPTED_FOR_ABORT = 10
# A Workday job's detail page is re-fetched at most this often; in between, cached per-profile verdicts are reused.
ENRICH_TTL = timedelta(days=7)
# A blocked board falls back to its cached listing (its jobs stay listed, matchable and unpruned) only while the
# cache is younger than the job-pruning window. shortcut: assumes the jobs are still live while we can't look.
BLOCKED_CACHE_MAX_AGE = timedelta(days=30)
# Flat and short: blocks have cleared within a day, and a probe costs one request per pod.
BACKOFF_DAYS = 1


def _tag(jobs: list[JobPosting], company: Company | dict) -> list[JobPosting]:
    for job in jobs:
        job["company_id"] = company["id"]
        job["company_name"] = company["name"]
        job["ats_platform"] = company["ats_platform"]
    return jobs


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
    return _tag(jobs, company)


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
    # - Workday: no pool; WorkdayClient paces request starts per pod (wd1, wd5, ...). A shared pool on top
    #   would let the busiest pod hold every slot and stall the others.
    # - Ashby: independent serialized pacing lock (0.5s) to prevent 429s and soft-throttle drops
    async with make_http_client() as http:
        fast_sem = asyncio.Semaphore(30)
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
                    state = workday_states.setdefault(c["id"], {})
                    if state.get("queries") and not is_hot(state) and not full_scan_due(state):
                        # A5: a cold board is scanned only on its staggered weekly full scan
                        return _tag(WorkdayClient.cached_jobs(c["ats_identifier"], state), c)
                    return await fetch_company(http, c, state, countries)
                return await asyncio.wait_for(fetch_company(http, c), timeout=PER_COMPANY_TIMEOUT)
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
                        "blocked": True,
                    }
                )
            state = (workday_states or {}).get(company.get("id")) or {}
            if company.get("ats_platform") == "workday" and _cache_fresh(state):
                all_jobs.extend(_tag(WorkdayClient.cached_jobs(company["ats_identifier"], state), company))
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
    companies = _select_platforms(queries.get_all_companies(), args.platforms, args.skip_platforms)
    # A pod is dropped after a few challenges, so a fixed order would only ever try the same few boards on it.
    random.shuffle(companies)
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

    workday_states: dict[int, dict] = {}
    backoff: dict[str, dict] = {}
    # A run that skips Workday must not load this state: saving its stale copy at the end would overwrite
    # whatever a Workday run stored in the meantime.
    if any(c.get("ats_platform") == "workday" for c in companies):
        try:
            workday_states = queries.get_workday_board_states()
        except Exception as e:  # first run before the schema is applied, or a read failure: scan without the cache
            logger.warning("Could not load Workday board state, scanning without it: %s", e)
        try:
            backoff = queries.get_workday_pod_backoff()
        except Exception as e:
            logger.warning("Could not load Workday pod back-off, probing every pod: %s", e)
    now = datetime.now(timezone.utc)
    for pod, b in backoff.items():
        # B9: no requests while backed off; afterwards one challenge (not five) blocks the pod again
        if b["until"] > now:
            challenge_tracker.block(pod)
        else:
            challenge_tracker.prime(pod)
    if backoff:
        logger.info(
            "Workday pods in back-off: %s",
            ", ".join(
                f"{p} until {b['until']:%Y-%m-%d}" if b["until"] > now else f"{p} (probe)" for p, b in backoff.items()
            ),
        )

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
            "%d of %d companies were not scraped, %s: their host is in back-off or answered with a Cloudflare "
            "challenge (hosts that challenged this run: %s). They are skipped, not failures.",
            len(blocked),
            len(companies),
            ", ".join(f"{p}={n}" for p, n in sorted(by_platform.items())),
            ", ".join(sorted(challenge_tracker.challenged)) or "none",
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
    if attempted >= MIN_ATTEMPTED_FOR_ABORT and len(failures) > attempted * FAILURE_RATE_LIMIT:
        logger.error("Failure rate too high — aborting.")
        # Still persist: a run that aborts because Workday blocked nearly everything must record the back-off.
        _save_workday(args, jobs, workday_states, backoff, now)
        return 1

    logger.info("Fetched %d live job postings.", len(jobs))

    # Ashby/SmartRecruiters-style listings ship without descriptions; fetch
    # details only for candidates passing the union prefilter across active users.
    from jobs.enrich import enrich_jobs, extract_compensation, passes_prefilter_multiuser

    # Each user's filters layered over the default profile, so a missing key falls back instead of raising.
    user_filters = {id(u): {**profile, **(u.get("profile_filters") or {})} for u in active_users}
    hashes = {id(u): _profile_hash(user_filters[id(u)]) for u in active_users}
    candidates = [j for j in jobs if passes_prefilter_multiuser(j, active_users, base=profile)]
    for j in candidates:  # A5: boards producing candidates stay on the daily scan
        if j.get("ats_platform") == "workday" and j.get("company_id") in workday_states:
            workday_states[j["company_id"]]["last_candidate_at"] = now.isoformat()
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
        try:
            u_matches = [j for j in jobs if _match(j, user_filters[id(u)], hashes[id(u)])]
        except Exception:  # one malformed profile must not stop everyone else's digest
            logger.exception("Matching failed for user %s; skipping this user today.", u.get("id"))
            u_matches = []
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

    _save_workday(args, jobs, workday_states, backoff, now)
    if args.dry_run:
        for u in active_users:
            u_matches = user_match_map.get(u.get("id"), [])
            logger.info("[dry-run] User %s matches %d job(s).", u.get("email"), len(u_matches))
        logger.info("[dry-run] no DB writes, no email.")
        return 0

    new_jobs = queries.upsert_jobs(all_matched_jobs)
    stale = queries.delete_stale_jobs(days=30)
    closed = queries.close_unlisted_applications(days=30)
    logger.info(
        "Stored %d new / %d total matched; pruned %d stale; closed %d unlisted application(s).",
        len(new_jobs),
        len(all_matched_jobs),
        stale,
        closed,
    )

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
                # No platform accepts applications without the employer's API key (#48), so all are To Apply.
                app_stage_items.append({"job_posting_id": jid, "status": "manual_apply"})

        if match_records:
            queries.upsert_user_matches(uid, match_records)
        if app_stage_items:
            queries.stage_user_applications(uid, app_stage_items)

    # Remote-browser apply spike (#129): only for allowlisted users; never stops the digest.
    from jobs.apply.fill_plan import allowlisted_user_ids, build_fill_plans

    if allowlisted_user_ids():
        try:
            logger.info("Built %d fill plan(s).", await build_fill_plans(active_users))
        except Exception:
            logger.exception("Fill plans failed; the digest continues.")

    if args.no_email:
        logger.info("--no-email: jobs and matches stored; the next digest run sends them.")
        return 0

    from jobs.notify import email_configured, send_email_digest, send_user_digest

    if not email_configured(require_digest_email=any(not u.get("id") for u in active_users)):
        logger.warning("Matches found but no delivery channel — they will be retried.")
        return 1

    sent_count = 0
    for u in active_users:
        uid = u.get("id")
        if uid:
            try:
                unnotified = queries.get_user_unnotified_matches(uid)
                activity = queries.get_user_recent_application_activity(uid)
                msg_id = send_user_digest(u, unnotified, activity, boards=attempted)
            except Exception:  # e.g. SMTP rejects one address; the remaining users must still get theirs
                logger.exception("Digest failed for user %s; matches stay unnotified for the next run.", uid)
                continue
            if msg_id:
                sent_count += 1
                if unnotified:
                    queries.mark_user_matches_notified(uid, [j["id"] for j in unnotified])
                logger.info("Personalized digest sent to %s (%d new matches).", u.get("email"), len(unnotified))
        else:
            # Not just this run's new jobs: Workday runs store jobs with --no-email for this digest to send.
            pending = queries.get_unnotified_jobs()
            if pending:
                send_email_digest(pending)
                queries.mark_notified([j["id"] for j in pending])
                sent_count += 1
                logger.info("Email digest sent for %d jobs.", len(pending))

    logger.info("Notification stage finished. Digests sent: %d.", sent_count)
    return 0


def _select_platforms(companies: list, only: str | None, skip: str | None) -> list:
    """Filter companies by comma-separated platform lists (--platforms / --skip-platforms)."""
    keep = {p.strip() for p in only.split(",")} if only else None
    drop = {p.strip() for p in skip.split(",")} if skip else set()
    return [
        c for c in companies if (keep is None or c.get("ats_platform") in keep) and c.get("ats_platform") not in drop
    ]


def _facet_countries(active_users: list[dict], profile: dict) -> set[str] | None:
    """Lowercase country names to narrow large Workday boards with, or None to not narrow.

    Built from every user's locations plus eligible_regions (non-country entries simply match no facet).
    A user without eligible_regions may have city-only locations whose country we can't infer, so then
    nothing is narrowed. Narrowing drops postings in other countries, "Remote - <other country>" included.
    """
    out: set[str] = set()
    for u in active_users:
        f = {**profile, **(u.get("profile_filters") or {})}
        if not f.get("eligible_regions"):
            return None
        out |= {str(x).strip().lower() for x in [*f["eligible_regions"], *(f.get("locations") or [])]}
    return out or None


def _save_workday(args, jobs: list[dict], states: dict[int, dict], backoff: dict[str, dict], now: datetime) -> None:
    """Persist board state and pod back-off. Failures only cost requests next run, so they never block the run."""
    # Blocked: reached the consecutive-challenge limit, or challenged us without ever answering normally (a pod
    # hosting only a few boards never reaches the limit, but still turned us away every time).
    blocked_pods = {
        p
        for p in challenge_tracker.challenged
        if challenge_tracker.is_blocked(p) or p not in challenge_tracker.answered
    }
    pod_upserts, pod_deletes = _plan_backoff(backoff, blocked_pods, challenge_tracker.answered, now)
    for pod, b in pod_upserts.items():
        logger.warning("Workday pod %s challenged us: no requests to it for %d day(s).", pod, b["days"])
    if args.dry_run:
        logger.info("[dry-run] Workday board state and pod back-off not saved (%d boards).", len(states))
        return
    _record_enrichment(jobs, states)
    try:
        queries.save_workday_board_states(states)
    except Exception as e:
        logger.warning("Could not save Workday board state: %s", e)
    try:
        queries.save_workday_pod_backoff(pod_upserts, pod_deletes)
    except Exception as e:
        logger.warning("Could not save Workday pod back-off: %s", e)


def _cache_fresh(state: dict) -> bool:
    last = state.get("full_scan_at")
    return bool(state.get("queries") and last) and (
        datetime.now(timezone.utc) - datetime.fromisoformat(last) < BLOCKED_CACHE_MAX_AGE
    )


def _plan_backoff(
    backoff: dict[str, dict], blocked: set[str], answered: set[str], now: datetime
) -> tuple[dict[str, dict], set[str]]:
    """New back-off rows for Workday pods blocked this run, and rows to clear."""
    upserts = {}
    for pod in blocked:
        if not pod.endswith(".myworkdayjobs.com"):
            continue
        upserts[pod] = {"until": now + timedelta(days=BACKOFF_DAYS), "days": BACKOFF_DAYS}
    return upserts, {p for p in backoff if p in answered and p not in blocked}


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
    parser.add_argument("--platforms", type=str, default=None, help="comma-separated: scrape only these platforms")
    parser.add_argument("--skip-platforms", type=str, default=None, help="comma-separated: don't scrape these")
    parser.add_argument("--no-email", action="store_true", help="store jobs and matches but send no digest")
    args = parser.parse_args()

    return asyncio.run(run_pipeline(args))


if __name__ == "__main__":
    sys.exit(main())
