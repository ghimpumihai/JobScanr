"""SmartRecruiters job board client.

GET https://api.smartrecruiters.com/v1/companies/{company}/postings
Public unauthenticated API returning paginated job postings.
Detail descriptions are fetched per candidate via get_job_detail during enrichment.
"""

from scrapers.base import BaseClient, strip_html


def _format_location(location_dict: dict | None) -> str | None:
    if not location_dict:
        return None
    city = location_dict.get("city")
    country = location_dict.get("country")
    full_loc = location_dict.get("fullLocation")
    is_remote = location_dict.get("remote", False)

    parts = []
    if city and "remotely" not in city.lower():
        parts.append(city)
    if country:
        parts.append(country.upper())
    if is_remote and "remote" not in " ".join(parts).lower():
        parts.append("Remote")

    return ", ".join(parts) if parts else (full_loc or None)


class SmartRecruitersClient(BaseClient):
    async def get_jobs(self, ats_identifier: str) -> list[dict]:
        base_url = f"https://api.smartrecruiters.com/v1/companies/{ats_identifier}/postings"
        offset = 0
        limit = 100
        jobs = []

        while True:
            r = await self.request_with_retry(
                "GET",
                base_url,
                params={"limit": limit, "offset": offset},
            )
            r.raise_for_status()
            data = r.json()

            postings = data.get("content", [])
            for posting in postings:
                posting_id = str(posting["id"])
                title = (posting.get("name") or "").strip()
                department = (posting.get("department") or {}).get("label")
                location = _format_location(posting.get("location"))
                url = f"https://jobs.smartrecruiters.com/{ats_identifier}/{posting_id}"

                jobs.append({
                    "external_id": posting_id,
                    "title": title,
                    "location": location,
                    "department": department,
                    "url": url,
                    "description": None,
                })

            total_found = data.get("totalFound", 0)
            offset += len(postings)
            if not postings or offset >= total_found:
                break

        return jobs

    async def get_job_detail(self, ats_identifier: str, posting_id: str) -> dict | None:
        url = f"https://api.smartrecruiters.com/v1/companies/{ats_identifier}/postings/{posting_id}"
        r = await self.request_with_retry("GET", url)
        r.raise_for_status()
        data = r.json()

        job_ad = data.get("jobAd") or {}
        sections = job_ad.get("sections") or {}
        desc_parts = [
            (sections.get("companyDescription") or {}).get("text", ""),
            (sections.get("jobDescription") or {}).get("text", ""),
            (sections.get("qualifications") or {}).get("text", ""),
            (sections.get("additionalInformation") or {}).get("text", ""),
        ]
        description_html = "\n".join(p for p in desc_parts if p)

        return {
            "descriptionHtml": description_html if description_html else None,
            "externalUrl": data.get("postingUrl") or data.get("applyUrl"),
        }

