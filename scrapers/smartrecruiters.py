"""SmartRecruiters postings client.

GET https://api.smartrecruiters.com/v1/companies/{id}/postings?limit=100&offset=N
Paginated; the list endpoint has no descriptions (same trade-off as Ashby).
"""

from scrapers.base import BaseClient

PAGE_SIZE = 100
MAX_PAGES = 20


def _location(posting: dict) -> str | None:
    loc = posting.get("location") or {}
    parts = [loc.get("city"), loc.get("region"), loc.get("country")]
    named = [p for p in parts if p]
    remote = "Remote" if (posting.get("remote") or False) else None
    if remote and remote not in named:
        named.append(remote)
    return ", ".join(named) or None


class SmartRecruitersClient(BaseClient):
    async def get_jobs(self, ats_identifier: str) -> list[dict]:
        jobs: dict[str, dict] = {}
        for page in range(MAX_PAGES):
            r = await self.request_with_retry(
                "GET",
                f"https://api.smartrecruiters.com/v1/companies/{ats_identifier}/postings",
                params={"limit": PAGE_SIZE, "offset": page * PAGE_SIZE},
            )
            r.raise_for_status()
            body = r.json()
            content = body.get("content") or []
            for posting in content:
                department = (posting.get("department") or {}).get("label")
                jobs[str(posting["id"])] = {
                    "external_id": str(posting["id"]),
                    "title": (posting.get("name") or "").strip(),
                    "location": _location(posting),
                    "department": department,
                    "url": f"https://jobs.smartrecruiters.com/{ats_identifier}/{posting['id']}",
                    "description": None,
                }
            total = body.get("totalFound", len(content))
            if len(jobs) >= total or len(content) < PAGE_SIZE:
                break
        return list(jobs.values())
