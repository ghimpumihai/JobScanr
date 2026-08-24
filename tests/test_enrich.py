import asyncio

import jobs.enrich as enrich


def test_prefilter_gates_on_title_level_location():
    profile = {
        "titles": ["software engineer"],
        "levels": ["intern"],
        "locations": ["berlin", "remote"],
        "excluded_title_keywords": ["frontend"],
    }
    ok = {"title": "Software Engineer Intern", "location": "Berlin"}
    assert enrich.passes_prefilter(ok, profile)

    assert not enrich.passes_prefilter(
        {"title": "Software Engineer", "location": "Berlin"}, profile)          # no level
    assert not enrich.passes_prefilter(
        {"title": "Data Analyst Intern", "location": "Berlin"}, profile)        # wrong family
    assert not enrich.passes_prefilter(
        {"title": "Frontend Intern", "location": "Berlin"}, profile)            # excluded
    assert not enrich.passes_prefilter(
        {"title": "Software Engineer Intern", "location": "Tokyo"}, profile)    # location


def test_enrich_fills_description_and_metadata(monkeypatch):
    jobs = [{"title": "Junior Software Engineer", "location": "Berlin",
             "description": None, "ats_identifier": "acme",
             "external_id": "abc-123", "company_name": "Acme"}]

    async def fake_fetch(job, client):
        assert (job["ats_identifier"], job["external_id"]) == ("acme", "abc-123")
        return {"descriptionHtml": "<p>Great python team. Must be based in the US.</p>",
                "applicationDeadline": "2026-09-30",
                "compensationTiers": [{"tierSummary": "€50k–€60k"}]}

    monkeypatch.setattr(enrich, "_fetch_detail", fake_fetch)
    asyncio.run(enrich.enrich_jobs(jobs, client=None))

    assert jobs[0]["description"] == "Great python team. Must be based in the US."
    assert jobs[0]["application_deadline"] == "2026-09-30"
    assert jobs[0]["compensation"] == "€50k–€60k"


def test_enrich_silent_on_failure(monkeypatch):
    jobs = [{"title": "Junior Software Engineer", "location": "Berlin",
             "description": None, "ats_identifier": "acme",
             "external_id": "x", "company_name": "Acme"}]

    async def fake_fetch(job, client):
        return None

    monkeypatch.setattr(enrich, "_fetch_detail", fake_fetch)
    asyncio.run(enrich.enrich_jobs(jobs, client=None))
    assert jobs[0]["description"] is None


def test_workday_detail_updates_vague_location(monkeypatch):
    jobs = [{"title": "Junior Software Engineer", "location": "3 Locations",
             "description": None, "ats_identifier": "acme|wd5|AcmeCareers",
             "external_id": "slug_1", "external_path": "slug_1",
             "url": "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/AcmeCareers/job/slug_1",
             "company_name": "Acme"}]

    async def fake_fetch(job, client):
        return {"descriptionHtml": "<p>python</p>",
                "locationText": "Munich, Germany",
                "externalUrl": "https://acme.wd5.myworkdayjobs.com/AcmeCareers/job/Munich-Germany/slug_1"}

    monkeypatch.setattr(enrich, "_fetch_detail", fake_fetch)
    asyncio.run(enrich.enrich_jobs(jobs, client=None))
    assert jobs[0]["location"] == "Munich, Germany"
    # API link must be replaced by the human-facing page
    assert jobs[0]["url"] == "https://acme.wd5.myworkdayjobs.com/AcmeCareers/job/Munich-Germany/slug_1"
