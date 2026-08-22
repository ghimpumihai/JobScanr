"""Greenhouse job board client.

GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
Returns all jobs in one response (no pagination). `content` is base64 HTML.
"""

from scrapers.base import BaseClient, decode_html_field, strip_html


def _first_department(job: dict) -> str | None:
    deps = job.get("departments") or []
    return deps[0]["name"] if deps else None


class GreenhouseClient(BaseClient):
    async def get_jobs(self, ats_identifier: str) -> list[dict]:
        r = await self.request_with_retry(
            "GET",
            f"https://boards-api.greenhouse.io/v1/boards/{ats_identifier}/jobs",
            params={"content": "true"},
        )
        r.raise_for_status()
        jobs = []
        for job in r.json().get("jobs", []):
            location = (job.get("location") or {}).get("name")
            jobs.append({
                "external_id": str(job["id"]),
                "title": job.get("title", "").strip(),
                "location": location,
                "department": _first_department(job),
                "url": job.get("absolute_url"),
                "description": strip_html(decode_html_field(job.get("content"))),
            })
        return jobs
