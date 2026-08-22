"""Lever postings client.

GET https://api.lever.co/v0/postings/{company}?mode=json — single response, no pagination.
`descriptionPlain` is already plain text; fall back to stripping `description` HTML.
"""

from scrapers.base import BaseClient, strip_html


class LeverClient(BaseClient):
    async def get_jobs(self, ats_identifier: str) -> list[dict]:
        r = await self.request_with_retry(
            "GET",
            f"https://api.lever.co/v0/postings/{ats_identifier}",
            params={"mode": "json"},
        )
        r.raise_for_status()
        jobs = []
        for posting in r.json():
            categories = posting.get("categories") or {}
            description = posting.get("descriptionPlain")
            if not description:
                description = strip_html(posting.get("description"))
            location = categories.get("location")
            workplace = (posting.get("workplaceType") or "").replace("_", " ").title()
            if workplace and location and workplace.lower() not in location.lower():
                location = f"{location} ({workplace})"
            jobs.append({
                "external_id": str(posting["id"]),
                "title": (posting.get("text") or "").strip(),
                "location": location,
                "department": categories.get("department"),
                "url": posting.get("hostedUrl") or posting.get("applyUrl"),
                "description": description,
                "updated_at_raw": posting.get("updatedAt"),
            })
        return jobs
