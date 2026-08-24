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

    @staticmethod
    def _public_url(identifier: str, external_path: str) -> str:
        """Human-facing careers page, constructible straight from the listing —
        never depend on the flaky detail fetch for links."""
        tenant, wd, site = identifier.split("|")
        path = external_path if external_path.startswith("/") else f"/{external_path}"
        return f"https://{tenant}.{wd}.myworkdayjobs.com/{site}{path}"

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
                    "url": self._public_url(ats_identifier, external_path),
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
        """Full HTML description + human-facing URL for one posting."""
        base, _ = self._base(ats_identifier)
        try:
            r = await self.request_with_retry(
                "GET", f"{base}/job/{slug}", headers={"Accept": "application/json"})
            r.raise_for_status()
            body = r.json()
            info = body.get("jobPostingInfo") or {}
            desc = info.get("jobDescription")

            # Workday tenants serve inconsistent shapes: locations may be
            # dicts with a descriptor or bare strings.
            def descriptor(x):
                if isinstance(x, dict):
                    return x.get("descriptor")
                return x if isinstance(x, str) else None

            loc_parts = [descriptor(info.get("location"))] + [
                descriptor(l) for l in (info.get("additionalLocations") or [])]
            named = [x for x in loc_parts if x]

            out = {"descriptionHtml": desc}
            # The CXS /job/ path returns raw JSON; only externalUrl is the
            # human-facing page people can actually apply through.
            if info.get("externalUrl"):
                out["externalUrl"] = info["externalUrl"]
            if named:
                out["locationText"] = ", ".join(named)
            return out
        except Exception:
            return None


def normalize_description(detail: dict) -> str | None:
    """Shared HTML handling lives in scrapers.base."""
    from scrapers.base import strip_html

    return strip_html(detail.get("descriptionHtml"))
