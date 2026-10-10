import asyncio
from unittest.mock import patch
import httpx
import pytest

from scrapers.workday import WorkdayClient, normalize_description

SAMPLE_CXS_PAGE1 = {
    "total": 25,
    "jobPostings": [
        {
            "jobPostingId": f"JR10{i:02d}",
            "title": f"Software Engineer {i}",
            "externalPath": f"job/Munich/Software-Engineer_{i}",
            "locationsText": "Munich, Germany",
        }
        for i in range(20)
    ],
}

SAMPLE_CXS_PAGE2 = {
    "total": 25,
    "jobPostings": [
        {
            "jobPostingId": f"JR20{i:02d}",
            "title": f"Graduate Developer {i}",
            "externalPath": f"job/Berlin/Graduate-Developer_{i}",
            "locationsText": "Berlin, Germany",
        }
        for i in range(5)
    ],
}

SAMPLE_DETAIL = {
    "jobPostingInfo": {
        "jobDescription": "<p>Build high performance systems.</p>",
        "externalUrl": "https://nvidia.wd5.myworkdayjobs.com/en-US/Careers/job/JR1001",
        "location": {"descriptor": "Munich, Germany"},
        "additionalLocations": [
            {"descriptor": "Berlin, Germany"},
            "Frankfurt, Germany",
        ],
    }
}


def test_workday_url_helpers():
    base, tenant = WorkdayClient._base("nvidia|wd5|Careers")
    assert base == "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/Careers"
    assert tenant == "nvidia"

    public1 = WorkdayClient._public_url("nvidia|wd5|Careers", "job/JR1001")
    assert public1 == "https://nvidia.wd5.myworkdayjobs.com/Careers/job/JR1001"

    public2 = WorkdayClient._public_url("nvidia|wd5|Careers", "/job/JR1001")
    assert public2 == "https://nvidia.wd5.myworkdayjobs.com/Careers/job/JR1001"


def test_workday_get_jobs_pagination():
    offsets = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        payload = json.loads(request.content)
        offset = payload.get("offset")
        offsets.append(offset)
        if offset == 0:
            return httpx.Response(200, json=SAMPLE_CXS_PAGE1)
        elif offset == 20:
            return httpx.Response(200, json=SAMPLE_CXS_PAGE2)
        return httpx.Response(200, json={"total": 25, "jobPostings": []})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with patch("asyncio.sleep", return_value=None):
                client = WorkdayClient(http)
                return await client.get_jobs("nvidia|wd5|Careers")

    jobs = asyncio.run(run())
    assert len(jobs) == 25
    assert offsets == [0, 20]
    slugs = [j["external_path"] for j in jobs]
    assert "Software-Engineer_0" in slugs
    assert "Graduate-Developer_4" in slugs
    assert all(j["ats_identifier"] == "nvidia|wd5|Careers" for j in jobs)


def test_workday_get_job_detail_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/wday/cxs/nvidia/Careers/job/JR1001"
        return httpx.Response(200, json=SAMPLE_DETAIL)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = WorkdayClient(http)
            return await client.get_job_detail("nvidia|wd5|Careers", "JR1001")

    detail = asyncio.run(run())
    assert detail is not None
    assert detail["externalUrl"] == "https://nvidia.wd5.myworkdayjobs.com/en-US/Careers/job/JR1001"
    assert "Munich, Germany" in detail["locationText"]
    assert "Berlin, Germany" in detail["locationText"]
    assert "Frankfurt, Germany" in detail["locationText"]
    assert normalize_description(detail) == "Build high performance systems."


def test_workday_get_job_detail_error_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="Not Found")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with patch("asyncio.sleep", return_value=None):
                client = WorkdayClient(http)
                return await client.get_job_detail("nvidia|wd5|Careers", "JR999")

    detail = asyncio.run(run())
    assert detail is None
