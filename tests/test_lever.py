import asyncio
import httpx
import pytest

from scrapers.lever import LeverClient

SAMPLE_LEVER_DATA = [
    {
        "id": "lever-101",
        "text": "Junior Backend Developer ",
        "hostedUrl": "https://jobs.lever.co/spotify/lever-101",
        "applyUrl": "https://jobs.lever.co/spotify/lever-101/apply",
        "categories": {
            "location": "Stockholm",
            "department": "Engineering",
        },
        "workplaceType": "hybrid",
        "descriptionPlain": "We are looking for a Junior Backend Developer to join our team.",
        "description": "<p>Fallback HTML description</p>",
    },
    {
        "id": "lever-102",
        "text": "Software Engineer Intern",
        "hostedUrl": None,
        "applyUrl": "https://jobs.lever.co/spotify/lever-102/apply",
        "categories": {
            "location": "Remote - Europe",
            "department": "Data",
        },
        "workplaceType": "remote",
        "descriptionPlain": None,
        "description": "<p>Join our <b>data platform</b> team as an intern.</p>",
    },
]


def test_lever_get_jobs():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v0/postings/spotify"
        assert request.url.params.get("mode") == "json"
        return httpx.Response(200, json=SAMPLE_LEVER_DATA)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = LeverClient(http)
            return await client.get_jobs("spotify")

    jobs = asyncio.run(run())
    assert len(jobs) == 2

    j1 = jobs[0]
    assert j1["external_id"] == "lever-101"
    assert j1["title"] == "Junior Backend Developer"
    # workplaceType appended: "Stockholm (Hybrid)"
    assert j1["location"] == "Stockholm (Hybrid)"
    assert j1["department"] == "Engineering"
    assert j1["url"] == "https://jobs.lever.co/spotify/lever-101"
    assert j1["description"] == "We are looking for a Junior Backend Developer to join our team."

    j2 = jobs[1]
    assert j2["external_id"] == "lever-102"
    assert j2["title"] == "Software Engineer Intern"
    # "remote" workplaceType already in "Remote - Europe", so not redundantly appended
    assert j2["location"] == "Remote - Europe"
    assert j2["department"] == "Data"
    assert j2["url"] == "https://jobs.lever.co/spotify/lever-102/apply"
    # fallback to stripped HTML description
    assert j2["description"] == "Join our data platform team as an intern."
