"""Detail-page enrichment for listings that ship without descriptions.

Only Ashby today: its board-listing API omits descriptionHtml, but the
ApiJobPosting detail query returns it (plus application deadline and
compensation tiers we may surface later).

Enrichment runs AFTER a cheap title/location prefilter so we only pay
one extra request per plausible candidate, not per listing.
"""

import asyncio

import httpx

from config import PROFILE
from jobs.match import _any_word, _normalize
from scrapers.base import strip_html

DETAIL_QUERY = """query ApiJobPosting($organizationHostedJobsPageName: String!, $jobPostingId: String!) {
  jobPosting(organizationHostedJobsPageName: $organizationHostedJobsPageName, jobPostingId: $jobPostingId) {
    descriptionHtml
    applicationDeadline
    compensationTiers { tierSummary }
  }
}"""

CONCURRENCY = 8


def passes_prefilter(job: dict, p: dict | None = None) -> bool:
    """Cheap gate mirroring matches_profile's first three checks: whether a
    description-less listing is worth an enrichment request."""
    p = p or PROFILE
    title = _normalize(job.get("title"))
    headline = f"{title} {_normalize(job.get('location'))}"

    if not _any_word(p["titles"], title):
        return False
    if not _any_word(p.get("levels", []), title):
        return False
    if not any(loc in headline for loc in map(_normalize, p["locations"])):
        return False
    if _any_word(p.get("excluded_title_keywords", []), title):
        return False
    return True


def _needs_enrichment(job: dict) -> bool:
    return job.get("description") is None and job.get("ats_identifier") is not None


async def _fetch_ashby_detail(client: httpx.AsyncClient, org: str, posting_id: str,
                              timeout: float = 15.0) -> dict | None:
    try:
        r = await client.post(
            "https://jobs.ashbyhq.com/api/non-user-graphql",
            json={"operationName": "ApiJobPosting",
                  "variables": {"organizationHostedJobsPageName": org,
                                "jobPostingId": posting_id},
                  "query": DETAIL_QUERY},
        )
        if r.status_code != 200:
            return None
        return ((r.json().get("data") or {}).get("jobPosting")) or None
    except Exception:
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
            return job, await _fetch_ashby_detail(
                client, job["ats_identifier"], job["external_id"]
            )

    results = await asyncio.gather(*(one(t) for t in targets))
    lookup: dict[tuple[str, str], dict | None] = {}
    for job, detail in results:
        lookup[(job["ats_identifier"], job["external_id"])] = detail

    for job in jobs:
        key = (job.get("ats_identifier"), job.get("external_id"))
        if key in lookup and lookup[key]:
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
    return jobs
