"""Ashby job board client.

Ashby's public posting API (api.ashbyhq.com/jobPosting.list) requires auth.
The hosted job boards use an unauthenticated GraphQL endpoint instead:
POST https://jobs.ashbyhq.com/api/non-user-graphql, operation ApiJobBoardWithTeams.

The board listing has no descriptions; description stays None and the matcher
falls back to title+location. Enrichment for shortlisted jobs comes later.
"""

from scrapers.base import BaseClient

QUERY = """query ApiJobBoardWithTeams($organizationHostedJobsPageName: String!) {
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


class AshbyClient(BaseClient):
    async def get_jobs(self, ats_identifier: str) -> list[dict]:
        r = await self.request_with_retry(
            "POST",
            "https://jobs.ashbyhq.com/api/non-user-graphql",
            json={
                "operationName": "ApiJobBoardWithTeams",
                "variables": {"organizationHostedJobsPageName": ats_identifier},
                "query": QUERY,
            },
        )
        r.raise_for_status()
        body = r.json()
        if body.get("errors"):
            raise RuntimeError(f"ashby graphql error: {body['errors'][0]['message'][:120]}")
        board = (body.get("data") or {}).get("jobBoard")
        if board is None:
            raise RuntimeError(f"ashby: no such board '{ats_identifier}'")

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
