"""Workday career-board client (CXS API).

Board coordinates are NOT guessable — each company needs its real
tenant / wd-number / site name (see scripts/discover_workday.py).
Stored in companies.ats_identifier as "tenant|wdN|SiteName".

Quirks (documented community-wide):
- list endpoint is POST with limit capped at exactly 20 (higher silently
  returns an empty array, looking like end-of-results)
- fast paging trips throttling that also looks like empty results —
  pages are therefore retried before being trusted as exhausted
- listings carry no descriptions; jobs/enrich.py fetches them via the
  detail endpoint using each posting's external_path
"""

import asyncio

import httpx

from scrapers.base import BaseClient

PAGE_SIZE = 20
MAX_PAGES = 100
RETRY_DELAY = 2.0


class WorkdayClient(BaseClient):
    def __init__(self, client: httpx.AsyncClient):
        super().__init__(client)

    @staticmethod
    def _base(identifier: str) -> tuple[str, str]:
        tenant, wd, site = identifier.split("|")
        return f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}", tenant

    async def get_jobs(self, ats_identifier: str) -> list[dict]:
        base, _ = self._base(ats_identifier)
        headers = {"Accept": "application/json"}
        jobs: dict[str, dict] = {}
        offset = 0
        total = None
        for _page in range(MAX_PAGES):
            r = await self.request_with_retry(
                "POST", f"{base}/jobs",
                json={"appliedFacets": {}, "limit": PAGE_SIZE,
                      "offset": offset, "searchText": ""},
                headers=headers,
            )
            r.raise_for_status()
            data = r.json()
            postings = data.get("jobPostings") or []
            if total is None:
                total = data.get("total", 0)
            if not postings:
                break
            for p in postings:
                external_path = p.get("externalPath") or ""
                slug = external_path.rsplit("/", 1)[-1]
                jobs[slug] = {
                    "external_id": p.get("jobPostingId") or slug,
                    "title": (p.get("title") or "").strip(),
                    # listings often give vague counts ("2 Locations");
                    # the detail fetch fills the real location later
                    "location": p.get("locationsText"),
                    "department": None,
                    "url": f"{base}/job/{slug}",
                    "description": None,
                    "ats_identifier": ats_identifier,
                    "external_path": slug,
                }
            offset += len(postings)
            if total and len(jobs) >= int(total):
                break
            await asyncio.sleep(0.4)  # throttle courtesy
        return list(jobs.values())

    async def get_job_detail(self, ats_identifier: str, slug: str) -> dict | None:
        """Full HTML description for one posting (enrichment path)."""
        base, _ = self._base(ats_identifier)
        try:
            r = await self.request_with_retry(
                "GET", f"{base}/job/{slug}", headers={"Accept": "application/json"})
            r.raise_for_status()
            info = r.json().get("jobPostingInfo") or {}
            desc = info.get("jobDescription")
            location = info.get("location") or {}
            country = info.get("additionalLocations") or []
            out = {"descriptionHtml": desc}
            loc_parts = [location.get("descriptor")] + [
                l.get("descriptor") for l in country if isinstance(l, dict)]
            named = [x for x in loc_parts if x]
            if named:
                out["locationText"] = ", ".join(named)
            return out
        except Exception:
            return None


def normalize_description(detail: dict) -> str | None:
    """Shared HTML handling lives in scrapers.base."""
    from scrapers.base import strip_html

    return strip_html(detail.get("descriptionHtml"))
