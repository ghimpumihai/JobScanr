import pytest
import httpx
from scrapers.teamtailor import TeamtailorClient, _format_location


SAMPLE_FEED = {
    "version": "https://jsonfeed.org/version/1.1",
    "title": "BMW Techworks Romania",
    "home_page_url": "https://bmwtechworks.teamtailor.com/jobs",
    "feed_url": "https://bmwtechworks.teamtailor.com/jobs.json",
    "items": [
        {
            "id": "4e00b481-129f-4d1d-8a7e-c2022dcb98cc",
            "title": "Data Engineer",
            "url": "https://bmwtechworks.teamtailor.com/jobs/8394788-data-engineer",
            "date_published": "2026-09-17T13:42:05+03:00",
            "content_html": "<p>Build data pipelines with <b>Python</b>.</p>",
            "_jobposting": {
                "@context": "http://schema.org/",
                "@type": "JobPosting",
                "title": "Data Engineer",
                "description": "<p>Build data pipelines with <b>Python</b>.</p>",
                "identifier": {
                    "@type": "PropertyValue",
                    "name": "BMW Techworks Romania",
                    "value": 8394788,
                },
                "jobLocation": [
                    {
                        "@type": "Place",
                        "address": {
                            "@type": "PostalAddress",
                            "streetAddress": "Strada Ploiești 9",
                            "addressLocality": "Cluj-Napoca",
                            "addressCountry": "RO",
                            "addressRegion": "Romania",
                        },
                    }
                ],
            },
        }
    ],
}


def test_format_location_single_and_multi():
    single = {
        "jobLocation": {
            "address": {
                "addressLocality": "Cluj-Napoca",
                "addressCountry": "RO",
            }
        }
    }
    assert _format_location(single) == "Cluj-Napoca, RO"

    multi = {
        "jobLocation": [
            {"address": {"addressLocality": "Cluj-Napoca", "addressCountry": "RO"}},
            {"address": {"addressLocality": "Brașov", "addressCountry": "RO"}},
        ]
    }
    assert _format_location(multi) == "Cluj-Napoca, RO; Brașov, RO"


def test_format_location_telecommute():
    remote = {
        "jobLocationType": "TELECOMMUTE",
    }
    assert _format_location(remote) == "Remote"

    hybrid_remote = {
        "jobLocationType": "TELECOMMUTE",
        "jobLocation": [
            {"address": {"addressLocality": "Bucharest", "addressCountry": "RO"}}
        ],
    }
    assert _format_location(hybrid_remote) == "Bucharest, RO; Remote"


def test_format_location_empty():
    assert _format_location({}) is None


@pytest.mark.anyio
async def test_teamtailor_client_parses_jobs():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://bmwtechworks.teamtailor.com/jobs.json"
        return httpx.Response(200, json=SAMPLE_FEED)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TeamtailorClient(http)
        jobs = await client.get_jobs("bmwtechworks")
        assert len(jobs) == 1
        job = jobs[0]
        assert job["external_id"] == "4e00b481-129f-4d1d-8a7e-c2022dcb98cc"
        assert job["title"] == "Data Engineer"
        assert job["location"] == "Cluj-Napoca, RO"
        assert job["url"] == "https://bmwtechworks.teamtailor.com/jobs/8394788-data-engineer"
        assert job["description"] == "Build data pipelines with Python ."


@pytest.mark.anyio
async def test_teamtailor_client_pagination():
    page1 = {
        "items": [
            {
                "id": "1",
                "title": "Role 1",
                "url": "https://example.teamtailor.com/jobs/1",
                "content_html": "Desc 1",
            }
        ],
        "next_url": "https://example.teamtailor.com/jobs.json?page=2",
    }
    page2 = {
        "items": [
            {
                "id": "2",
                "title": "Role 2",
                "url": "https://example.teamtailor.com/jobs/2",
                "content_html": "Desc 2",
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if "page=2" in str(request.url):
            return httpx.Response(200, json=page2)
        return httpx.Response(200, json=page1)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TeamtailorClient(http)
        jobs = await client.get_jobs("example")
        assert len(jobs) == 2
        assert [j["title"] for j in jobs] == ["Role 1", "Role 2"]
