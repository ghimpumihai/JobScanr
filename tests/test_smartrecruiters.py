import pytest
import httpx
from scrapers.smartrecruiters import SmartRecruitersClient, _format_location


SAMPLE_POSTINGS_PAGE1 = {
    "totalFound": 2,
    "limit": 1,
    "offset": 0,
    "content": [
        {
            "id": "1001",
            "name": "Junior Software Engineer",
            "department": {"label": "Core Engineering"},
            "location": {
                "city": "Cluj-Napoca",
                "country": "ro",
                "remote": False,
                "fullLocation": "Cluj-Napoca, Romania",
            },
        }
    ],
}

SAMPLE_POSTINGS_PAGE2 = {
    "totalFound": 2,
    "limit": 1,
    "offset": 1,
    "content": [
        {
            "id": "1002",
            "name": "Frontend Developer",
            "department": {"label": "Web"},
            "location": {
                "city": "Employees can work remotely",
                "country": "ro",
                "remote": True,
                "fullLocation": "Remote, Romania",
            },
        }
    ],
}

SAMPLE_DETAIL = {
    "id": "1001",
    "name": "Junior Software Engineer",
    "postingUrl": "https://jobs.smartrecruiters.com/TestCo/1001-junior-software-engineer",
    "jobAd": {
        "sections": {
            "companyDescription": {"text": "<p>About TestCo</p>"},
            "jobDescription": {"text": "<p>We are hiring a junior SWE.</p>"},
            "qualifications": {"text": "<ul><li>Python</li><li>SQL</li></ul>"},
        }
    },
}


def test_format_location():
    loc1 = {"city": "Cluj-Napoca", "country": "ro", "remote": False}
    assert _format_location(loc1) == "Cluj-Napoca, RO"

    loc2 = {"city": "Employees can work remotely", "country": "ro", "remote": True}
    assert _format_location(loc2) == "RO, Remote"

    assert _format_location({}) is None
    assert _format_location(None) is None


@pytest.mark.anyio
async def test_smartrecruiters_get_jobs_pagination():
    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "offset=1" in url_str:
            return httpx.Response(200, json=SAMPLE_POSTINGS_PAGE2)
        return httpx.Response(200, json=SAMPLE_POSTINGS_PAGE1)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = SmartRecruitersClient(http)
        jobs = await client.get_jobs("testco")

        assert len(jobs) == 2
        assert jobs[0]["external_id"] == "1001"
        assert jobs[0]["title"] == "Junior Software Engineer"
        assert jobs[0]["location"] == "Cluj-Napoca, RO"
        assert jobs[0]["department"] == "Core Engineering"
        assert jobs[0]["url"] == "https://jobs.smartrecruiters.com/testco/1001"
        assert jobs[0]["description"] is None

        assert jobs[1]["external_id"] == "1002"
        assert jobs[1]["title"] == "Frontend Developer"


@pytest.mark.anyio
async def test_smartrecruiters_get_job_detail():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.smartrecruiters.com/v1/companies/testco/postings/1001"
        return httpx.Response(200, json=SAMPLE_DETAIL)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = SmartRecruitersClient(http)
        detail = await client.get_job_detail("testco", "1001")

        assert detail is not None
        assert "About TestCo" in detail["descriptionHtml"]
        assert "We are hiring a junior SWE." in detail["descriptionHtml"]
        assert "Python" in detail["descriptionHtml"]
        assert detail["externalUrl"] == "https://jobs.smartrecruiters.com/TestCo/1001-junior-software-engineer"

