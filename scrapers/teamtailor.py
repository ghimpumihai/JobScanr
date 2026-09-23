"""Teamtailor job board client.

GET https://{ats_identifier}.teamtailor.com/jobs.json
Teamtailor provides an unauthenticated JSON Feed (v1.1) for career boards.
Pagination follows `next_url` when present.
"""

from scrapers.base import BaseClient, strip_html


def _format_location(job_posting: dict) -> str | None:
    locations = job_posting.get("jobLocation")
    if not locations:
        if job_posting.get("jobLocationType") == "TELECOMMUTE":
            return "Remote"
        return None

    if isinstance(locations, dict):
        locations = [locations]

    loc_strs = []
    for loc in locations:
        if not isinstance(loc, dict):
            continue
        address = loc.get("address") or {}
        parts = []
        city = address.get("addressLocality")
        country = address.get("addressCountry")
        if city:
            parts.append(city)
        if country and country not in parts:
            parts.append(country)
        if parts:
            loc_strs.append(", ".join(parts))
        elif loc.get("name"):
            loc_strs.append(loc["name"])

    if job_posting.get("jobLocationType") == "TELECOMMUTE":
        if "Remote" not in loc_strs:
            loc_strs.append("Remote")

    return "; ".join(loc_strs) if loc_strs else None


class TeamtailorClient(BaseClient):
    async def get_jobs(self, ats_identifier: str) -> list[dict]:
        if ats_identifier.startswith("http://") or ats_identifier.startswith("https://"):
            url = f"{ats_identifier.rstrip('/')}/jobs.json"
        else:
            url = f"https://{ats_identifier}.teamtailor.com/jobs.json"

        jobs = []
        page_count = 0
        max_pages = 10

        while url and page_count < max_pages:
            r = await self.request_with_retry("GET", url)
            r.raise_for_status()
            data = r.json()

            for item in data.get("items", []):
                job_posting = item.get("_jobposting") or {}
                external_id = str(item.get("id") or job_posting.get("identifier", {}).get("value") or "")
                title = (item.get("title") or job_posting.get("title") or "").strip()
                description_html = item.get("content_html") or job_posting.get("description")
                department = item.get("department") or job_posting.get("occupationalCategory")

                jobs.append({
                    "external_id": external_id,
                    "title": title,
                    "location": _format_location(job_posting),
                    "department": department,
                    "url": item.get("url"),
                    "description": strip_html(description_html),
                })

            url = data.get("next_url")
            page_count += 1

        return jobs

