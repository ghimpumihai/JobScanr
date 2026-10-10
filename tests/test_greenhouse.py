import asyncio
import base64
import httpx
import pytest

from scrapers.greenhouse import GreenhouseClient, _first_department

SAMPLE_GREENHOUSE_DATA = {
    "jobs": [
        {
            "id": 123456,
            "title": "Software Engineer, Infrastructure ",
            "absolute_url": "https://boards.greenhouse.io/stripe/jobs/123456",
            "location": {"name": "Dublin, Ireland"},
            "departments": [
                {"id": 1, "name": "Infrastructure"},
                {"id": 2, "name": "Core"},
            ],
            "content": base64.b64encode(b"&lt;p&gt;Build global payment systems.&lt;/p&gt;").decode("ascii"),
        },
        {
            "id": 123457,
            "title": "Frontend Engineer",
            "absolute_url": "https://boards.greenhouse.io/stripe/jobs/123457",
            "location": {"name": "Remote - Europe"},
            "departments": [],
            "content": "<p>Plain HTML description without base64.</p>",
        },
    ]
}


def test_first_department():
    assert _first_department({"departments": [{"name": "Eng"}]}) == "Eng"
    assert _first_department({"departments": []}) is None
    assert _first_department({}) is None


def test_greenhouse_get_jobs():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/boards/stripe/jobs"
        assert request.url.params.get("content") == "true"
        return httpx.Response(200, json=SAMPLE_GREENHOUSE_DATA)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = GreenhouseClient(http)
            return await client.get_jobs("stripe")

    jobs = asyncio.run(run())
    assert len(jobs) == 2

    j1 = jobs[0]
    assert j1["external_id"] == "123456"
    assert j1["title"] == "Software Engineer, Infrastructure"
    assert j1["location"] == "Dublin, Ireland"
    assert j1["department"] == "Infrastructure"
    assert j1["url"] == "https://boards.greenhouse.io/stripe/jobs/123456"
    assert j1["description"] == "Build global payment systems."

    j2 = jobs[1]
    assert j2["external_id"] == "123457"
    assert j2["title"] == "Frontend Engineer"
    assert j2["department"] is None
    assert j2["description"] == "Plain HTML description without base64."
