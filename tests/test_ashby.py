import asyncio
from unittest.mock import patch
import httpx
import pytest

from scrapers.ashby import AshbyClient, normalize_description, GRAPHQL_URL

SAMPLE_BOARD_DATA = {
    "data": {
        "jobBoard": {
            "teams": [
                {"id": "team-1", "name": "Engineering"},
                {"id": "team-2", "name": "Product"},
            ],
            "jobPostings": [
                {
                    "id": "post-101",
                    "title": "Software Engineer, Backend",
                    "teamId": "team-1",
                    "locationName": "Munich, Germany",
                    "workplaceType": "Hybrid",
                    "employmentType": "FullTime",
                    "secondaryLocations": [
                        {"locationName": "Berlin, Germany"},
                    ],
                },
                {
                    "id": "post-102",
                    "title": "Product Designer",
                    "teamId": "team-2",
                    "locationName": "Remote - Europe",
                    "workplaceType": "Remote",
                    "employmentType": "FullTime",
                    "secondaryLocations": [],
                },
            ],
        }
    }
}

SAMPLE_DETAIL_DATA = {
    "data": {
        "jobPosting": {
            "descriptionHtml": "<p>We are seeking a <strong>Software Engineer</strong> to join us.</p>",
            "applicationDeadline": "2026-12-31",
            "compensationTiers": [
                {"tierSummary": "€70,000 - €85,000"}
            ],
        }
    }
}


def test_ashby_get_jobs_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == GRAPHQL_URL
        assert request.method == "POST"
        return httpx.Response(200, json=SAMPLE_BOARD_DATA)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = AshbyClient(http)
            return await client.get_jobs("acme")

    jobs = asyncio.run(run())
    assert len(jobs) == 2
    j1 = jobs[0]
    assert j1["external_id"] == "post-101"
    assert j1["title"] == "Software Engineer, Backend"
    assert j1["department"] == "Engineering"
    assert j1["location"] == "Munich, Germany, Berlin, Germany"
    assert j1["url"] == "https://jobs.ashbyhq.com/acme/post-101"
    assert j1["ats_identifier"] == "acme"
    assert j1["description"] is None

    j2 = jobs[1]
    assert j2["external_id"] == "post-102"
    assert j2["department"] == "Product"
    assert j2["location"] == "Remote - Europe"


def test_ashby_get_jobs_soft_throttling_retry():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            # Ashby soft throttle: HTTP 200 with null payload
            return httpx.Response(200, json={"data": {"jobBoard": None}})
        return httpx.Response(200, json=SAMPLE_BOARD_DATA)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with patch("asyncio.sleep", return_value=None):
                client = AshbyClient(http)
                return await client.get_jobs("acme")

    jobs = asyncio.run(run())
    assert len(jobs) == 2
    assert calls == 2


def test_ashby_graphql_error_raises_runtime_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errors": [{"message": "Invalid organization"}]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = AshbyClient(http)
            await client.get_jobs("unknown-org")

    with pytest.raises(RuntimeError, match="ashby graphql error: Invalid organization"):
        asyncio.run(run())


def test_ashby_get_job_detail_and_normalize():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SAMPLE_DETAIL_DATA)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = AshbyClient(http)
            return await client.get_job_detail("acme", "post-101")

    detail = asyncio.run(run())
    assert detail is not None
    assert detail["applicationDeadline"] == "2026-12-31"
    assert normalize_description(detail) == "We are seeking a Software Engineer to join us."
