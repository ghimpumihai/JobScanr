"""Ashby job board client.

Ashby's public posting API (api.ashbyhq.com/jobPosting.list) requires auth.
The hosted job boards use an unauthenticated GraphQL endpoint instead:
POST https://jobs.ashbyhq.com/api/non-user-graphql

Ashby soft-throttles concurrent bursts by returning HTTP 200 with null
data instead of 429s — every call therefore retries on empty payloads.

The board listing has no descriptions; jobs/enrich.py fetches them per
candidate via the ApiJobPosting detail query.
"""

import asyncio

from scrapers.base import BaseClient, strip_html

GRAPHQL_URL = "https://jobs.ashbyhq.com/api/non-user-graphql"
RETRIES = 3
RETRY_DELAY = 1.0

BOARD_QUERY = """query ApiJobBoardWithTeams($organizationHostedJobsPageName: String!) {
  jobBoard: jobBoardWithTeams(organizationHostedJobsPageName: $organizationHostedJobsPageName) {
    teams { id name }
    jobPostings {
      id
      title
      teamId
      locationName
      workplaceType
      employmentType
      secondaryLocations { locationName }
    }
  }
}"""

DETAIL_QUERY = """query ApiJobPosting($organizationHostedJobsPageName: String!, $jobPostingId: String!) {
  jobPosting(organizationHostedJobsPageName: $organizationHostedJobsPageName, jobPostingId: $jobPostingId) {
    descriptionHtml
    applicationDeadline
    compensationTiers { tierSummary }
  }
}"""


class AshbyClient(BaseClient):
    async def _graphql(self, operation: str, query: str, variables: dict,
                       data_key: str) -> dict:
        delay = RETRY_DELAY
        for _ in range(RETRIES):
            r = await self.request_with_retry(
                "POST", GRAPHQL_URL,
                json={"operationName": operation, "variables": variables,
                      "query": query},
            )
            r.raise_for_status()
            body = r.json()
            if body.get("errors"):
                raise RuntimeError(
                    f"ashby graphql error: {body['errors'][0]['message'][:120]}")
            data = (body.get("data") or {}).get(data_key)
            if data is not None:
                return data
            await asyncio.sleep(delay)  # soft-throttled: back off and retry
            delay *= 2
        raise RuntimeError(f"ashby: throttled after {RETRIES} retries ({variables})")

    async def get_jobs(self, ats_identifier: str) -> list[dict]:
        board = await self._graphql(
            "ApiJobBoardWithTeams", BOARD_QUERY,
            {"organizationHostedJobsPageName": ats_identifier}, "jobBoard",
        )
        team_names = {t["id"]: t["name"] for t in board.get("teams", [])}
        jobs = []
        for posting in board.get("jobPostings", []):
            locations = [posting.get("locationName") or ""]
            locations += [s["locationName"] for s in posting.get("secondaryLocations") or []]
            jobs.append({
                "external_id": str(posting["id"]),
                "title": (posting.get("title") or "").strip(),
                "location": ", ".join(loc for loc in locations if loc) or None,
                "department": team_names.get(posting.get("teamId")),
                "url": f"https://jobs.ashbyhq.com/{ats_identifier}/{posting['id']}",
                "description": None,
                "ats_identifier": ats_identifier,  # used by detail enrichment
            })
        return jobs

    async def get_job_detail(self, ats_identifier: str, posting_id: str) -> dict | None:
        """Full description + deadline + compensation for one posting."""
        return await self._graphql(
            "ApiJobPosting", DETAIL_QUERY,
            {"organizationHostedJobsPageName": ats_identifier,
             "jobPostingId": posting_id},
            "jobPosting",
        )


def normalize_description(detail: dict) -> str | None:
    """Shared with jobs/enrich.py so HTML handling stays in one place."""
    return strip_html(detail.get("descriptionHtml"))
