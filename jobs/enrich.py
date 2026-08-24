"""Detail-page enrichment for listings that ship without descriptions.

Only Ashby today: its board-listing API omits descriptionHtml, but the
ApiJobPosting detail query returns it (plus application deadline and
compensation tiers we may surface later).

Enrichment runs AFTER a cheap title/location prefilter so we only pay
one extra request per plausible candidate, not per listing.
"""

import asyncio
import re

import httpx

from config import PROFILE
from jobs.match import _any_word, _normalize
from scrapers.base import strip_html

CONCURRENCY = 8

# Salary ranges embedded in description text ("€48k – €55k",
# "$120,000-$140,000", "£40-45k"). Employers rarely fill structured
# salary fields, but many paste ranges into the description.
SALARY_RE = re.compile(
    r"(?:€|\$|£|EUR|USD|GBP)\s?\d{1,3}(?:[.,]\d{3})*(?:\s?[kK])?"
    r"(?:\s?[–\-—to]{1,3}\s?"
    r"(?:€|\$|£|EUR|USD|GBP)?\s?\d{1,3}(?:[.,]\d{3})*(?:\s?[kK])?)?"
)


def _parse_amount(s: str) -> int | None:
    """'48k' -> 48000 · '120,000' -> 120000 · 'x' -> None"""
    s = s.strip()
    mult = 1000 if s[-1:] in ("k", "K") else 1
    digits = re.sub(r"[^\d]", "", s)
    return int(digits) * mult if digits else None


def extract_compensation(text: str | None) -> str | None:
    """First plausible ANNUAL salary range found in free text.

    Deliberately rejects the classic false positives: company-metric
    numbers ('€800M+ in ARR', '40K+ customers'), hourly rates, and any
    figure too small to be an annual salary."""
    if not text:
        return None
    t = re.sub(r"\s+", " ", text)

    for m in SALARY_RE.finditer(t):
        token = m.group(0)
        # '€800M+', '$2B+' — company metrics, not salaries
        rest = t[m.end():m.end() + 3].lstrip()
        if rest[:1] in ("M", "B"):
            continue
        values = [_parse_amount(x) for x in re.findall(r"\d[\d,.]*\s?[kK]?", token)]
        values = [v for v in values if v]
        if not values:
            continue
        if max(values) >= 1_000_000:
            continue
        # bare '€800' is a monthly stipend at best; '€48k' or '£67,575' is real
        if max(values) < 10_000 and not re.search(r"[kK]\s?$", token):
            continue
        # hourly gigs
        if re.match(r"\s*/?\s*h(\.|our)?", t[m.end():], re.IGNORECASE):
            continue
        # revenue/funding marketing copy
        context = t[max(0, m.start() - 45):m.end() + 45]
        if re.search(r"\b(ARR|MRR|revenue|funding|raised|valuation)\b",
                     context, re.IGNORECASE):
            continue
        return re.sub(r"\s+", "", token) or None
    return None


def passes_prefilter(job: dict, p: dict | None = None) -> bool:
    """Cheap gate mirroring matches_profile's first three checks: whether a
    description-less listing is worth an enrichment request.

    Workday listings often carry vague locations ("2 Locations") that only
    the detail fetch resolves — so the location gate is waived there."""
    p = p or PROFILE
    title = _normalize(job.get("title"))
    headline = f"{title} {_normalize(job.get('location'))}"
    is_workday = "|" in (job.get("ats_identifier") or "")

    if not _any_word(p["titles"], title):
        return False
    if not _any_word(p.get("levels", []), title):
        return False
    if not is_workday and not any(
            loc in headline for loc in map(_normalize, p["locations"])):
        return False
    if _any_word(p.get("excluded_title_keywords", []), title):
        return False
    return True


def _needs_enrichment(job: dict) -> bool:
    return job.get("description") is None and job.get("ats_identifier") is not None


async def _fetch_detail(job: dict, client: httpx.AsyncClient) -> dict | None:
    ident = job["ats_identifier"]
    # Detail endpoints throttle intermittently right after big scrapes;
    # back off patiently — candidates are few and links no longer depend
    # on this succeeding (workday builds those from the listing itself).
    for attempt in range(3):
        try:
            if "|" in ident:  # workday: "tenant|wdN|Site"
                from scrapers.workday import WorkdayClient

                detail = await WorkdayClient(client).get_job_detail(
                    ident, job["external_path"])
            else:
                from scrapers.ashby import AshbyClient

                detail = await AshbyClient(client).get_job_detail(
                    ident, job["external_id"])
            if detail is not None and detail.get("descriptionHtml"):
                return detail
        except Exception:
            pass
        await asyncio.sleep(3.0 * (attempt + 1))
    return None


async def enrich_jobs(jobs: list[dict], client: httpx.AsyncClient,
                      p: dict | None = None) -> list[dict]:
    """Fill descriptions for candidates lacking them. Failures are silent:
    an unenriched job still gets matched on title/location."""
    targets = [j for j in jobs if passes_prefilter(j, p) and _needs_enrichment(j)]
    if not targets:
        return jobs

    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(job: dict):
        async with sem:
            return job, await _fetch_detail(job, client)

    results = await asyncio.gather(*(one(t) for t in targets))
    lookup: dict[tuple[str, str], dict | None] = {}
    failures = 0
    for job, detail in results:
        lookup[(job["ats_identifier"], job["external_id"])] = detail
        if detail is None or not detail.get("descriptionHtml"):
            failures += 1
    if failures:
        print(f"  enrichment: {failures}/{len(targets)} detail fetches incomplete "
              f"(links/descriptions may be stale)")

    for job in jobs:
        key = (job.get("ats_identifier"), job.get("external_id"))
        if key not in lookup or not lookup[key]:
            continue
        detail = lookup[key]
        desc = detail.get("descriptionHtml")
        if desc:
            job["description"] = strip_html(desc)
        if detail.get("applicationDeadline"):
            job["application_deadline"] = detail["applicationDeadline"]
        tiers = detail.get("compensationTiers") or []
        summaries = [t.get("tierSummary") for t in tiers if t.get("tierSummary")]
        if summaries:
            job["compensation"] = "; ".join(summaries)
        if detail.get("locationText"):
            job["location"] = detail["locationText"]
        if detail.get("externalUrl"):
            # Workday's API path returns raw JSON in a browser; swap in the
            # human-facing careers URL the detail response provides.
            job["url"] = detail["externalUrl"]
    return jobs
