"""Unit tests for typed data models."""

from models import Company, EnrichedJobPosting, JobPosting


def test_company_model():
    company: Company = {
        "id": 1,
        "name": "Stripe",
        "ats_platform": "greenhouse",
        "ats_identifier": "stripe",
        "career_url": "https://stripe.com/jobs",
    }
    assert isinstance(company, dict)
    assert company["name"] == "Stripe"
    assert company["ats_platform"] == "greenhouse"
    assert company["id"] == 1


def test_company_seed_alias():
    company: Company = {
        "name": "Datadog",
        "company_name": "Datadog",
        "ats_platform": "greenhouse",
        "ats_identifier": "datadog",
    }
    assert company.get("company_name") == "Datadog"
    assert company.get("career_url") is None


def test_job_posting_model():
    job: JobPosting = {
        "external_id": "12345",
        "title": "Software Engineer Intern",
        "location": "Berlin, Germany",
        "department": "Engineering",
        "url": "https://example.com/jobs/12345",
        "description": "Develop reliable microservices.",
        "company_id": 42,
        "company_name": "Acme Corp",
        "ats_platform": "greenhouse",
    }
    assert isinstance(job, dict)
    assert job["external_id"] == "12345"
    assert job["title"] == "Software Engineer Intern"
    assert job.get("company_id") == 42


def test_enriched_job_posting_model():
    enriched: EnrichedJobPosting = {
        "external_id": "67890",
        "title": "Junior Backend Developer",
        "location": "Munich, Germany",
        "department": "Backend",
        "url": "https://example.com/jobs/67890",
        "description": "<p>Full detailed description fetched from detail API</p>",
        "compensation": "€65,000 - €75,000",
        "application_deadline": "2026-12-31",
    }
    assert isinstance(enriched, dict)
    assert enriched["compensation"] == "€65,000 - €75,000"
    assert enriched["application_deadline"] == "2026-12-31"
