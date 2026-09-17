import json
import pytest
from unittest.mock import AsyncMock, patch

from scripts.scan_and_fix_links import (
    apply_fixes_to_companies,
    construct_career_url,
    fingerprint_url_and_html,
    generate_candidate_identifiers,
    generate_report_markdown,
    parse_failures_from_log,
    recover_company,
    slugify,
)


def test_slugify():
    assert slugify("Sentry Inc.") == "sentryinc"
    assert slugify("Weights & Biases") == "weightsbiases"
    assert slugify("1Password") == "1password"


def test_parse_failures_from_log():
    log_text = """
Scraping 350 companies...
  FAIL Ada Health (greenhouse): Client error '404 Not Found' for url 'https://boards-api.greenhouse.io/v1/boards/adahealth/jobs'
  FAIL Sentry (ashby): RuntimeError: ashby graphql error: not found
  FAIL Ada Health (greenhouse): Client error '404 Not Found' for url 'https://boards-api.greenhouse.io/v1/boards/adahealth/jobs'
Fetched 120 live job postings.
"""
    failures = parse_failures_from_log(log_text)
    assert len(failures) == 2
    assert failures[0]["company_name"] == "Ada Health"
    assert failures[0]["ats_platform"] == "greenhouse"
    assert failures[0]["is_404"] is True

    assert failures[1]["company_name"] == "Sentry"
    assert failures[1]["ats_platform"] == "ashby"
    assert failures[1]["is_404"] is False


def test_fingerprint_url_and_html():
    # Greenhouse signature in URL
    gh = fingerprint_url_and_html("https://boards.greenhouse.io/acme", "")
    assert gh == ("greenhouse", "acme")

    # Ashby signature in HTML
    ash = fingerprint_url_and_html("https://careers.acme.com", '<a href="https://jobs.ashbyhq.com/acme-corp">Jobs</a>')
    assert ash == ("ashby", "acme-corp")

    # Lever signature in URL
    lev = fingerprint_url_and_html("https://jobs.lever.co/acme", "")
    assert lev == ("lever", "acme")

    # Workday signature in URL
    wd = fingerprint_url_and_html("https://adobe.wd5.myworkdayjobs.com/en-US/external_experienced", "")
    assert wd == ("workday", "adobe|wd5|external_experienced")


def test_generate_candidate_identifiers():
    comp = {"company_name": "Sentry", "ats_platform": "greenhouse", "ats_identifier": "sentry-io"}
    candidates = generate_candidate_identifiers(comp)
    assert "sentry" in candidates
    assert "getsentry" in candidates  # from ALIASES
    assert "sentryhq" in candidates
    assert "sentrycareers" in candidates
    assert "sentryio" in candidates  # dash stripped


def test_apply_fixes_to_companies():
    companies = [
        {"company_name": "Company A", "ats_platform": "greenhouse", "ats_identifier": "comp-a-old", "career_url": "http://a.com"},
        {"company_name": "Company B", "ats_platform": "lever", "ats_identifier": "comp-b", "career_url": "http://b.com"},
    ]
    recoveries = [
        {
            "company_name": "Company A",
            "old_platform": "greenhouse",
            "old_ident": "comp-a-old",
            "status": "recovered",
            "new_platform": "ashby",
            "new_ident": "compa",
            "new_career_url": "http://a.com/careers",
            "verification_detail": "10 jobs",
        },
        {
            "company_name": "Company B",
            "old_platform": "lever",
            "old_ident": "comp-b",
            "status": "unrecoverable",
            "reason": "404",
        },
    ]

    updated, count = apply_fixes_to_companies(companies, recoveries)
    assert count == 1
    assert updated[0]["ats_platform"] == "ashby"
    assert updated[0]["ats_identifier"] == "compa"
    assert updated[0]["career_url"] == "http://a.com/careers"
    assert updated[1]["ats_platform"] == "lever"
    assert updated[1]["ats_identifier"] == "comp-b"


def test_generate_report_markdown():
    recoveries = [
        {
            "company_name": "Company A",
            "old_platform": "greenhouse",
            "old_ident": "comp-a-old",
            "status": "recovered",
            "new_platform": "ashby",
            "new_ident": "compa",
            "verification_detail": "12 jobs",
            "reason": "fingerprinted",
        },
        {
            "company_name": "Company B",
            "old_platform": "lever",
            "old_ident": "comp-b",
            "status": "transient",
            "reason": "old endpoint now responding (5 jobs)",
        },
        {
            "company_name": "Company C",
            "old_platform": "greenhouse",
            "old_ident": "comp-c",
            "status": "unrecoverable",
            "reason": "no live ATS coordinates could be verified",
        },
    ]

    md = generate_report_markdown(recoveries, 3)
    assert "Successfully Verified & Fixed**: 1" in md
    assert "Transient (Self-Resolved)**: 1" in md
    assert "Unrecoverable (Requires Manual Review)**: 1" in md
    assert "| Company A | `greenhouse/comp-a-old` | `ashby/compa` | 12 jobs | fingerprinted |" in md
    assert "| Company C | `greenhouse/comp-c` | no live ATS coordinates could be verified |" in md


@pytest.mark.anyio
async def test_recover_company_transient():
    client = AsyncMock()
    comp = {"company_name": "TestCorp", "ats_platform": "greenhouse", "ats_identifier": "testcorp"}

    with patch("scripts.scan_and_fix_links.verify_ats", new=AsyncMock(return_value=(True, "5 jobs"))):
        res = await recover_company(client, comp)
        assert res["status"] == "transient"


@pytest.mark.anyio
async def test_recover_company_via_fingerprint():
    client = AsyncMock()
    comp = {
        "company_name": "TestCorp",
        "ats_platform": "greenhouse",
        "ats_identifier": "old_testcorp",
        "career_url": "https://testcorp.com/careers",
    }

    async def mock_verify(client, plat, ident):
        if plat == "greenhouse" and ident == "old_testcorp":
            return False, "404 Not Found"
        if plat == "ashby" and ident == "testcorp":
            return True, "15 jobs"
        return False, "Not Found"

    with patch("scripts.scan_and_fix_links.verify_ats", side_effect=mock_verify):
        with patch("scripts.scan_and_fix_links.probe_career_url",
                   new=AsyncMock(return_value=("ashby", "testcorp", "https://jobs.ashbyhq.com/testcorp"))):
            res = await recover_company(client, comp)
            assert res["status"] == "recovered"
            assert res["new_platform"] == "ashby"
            assert res["new_ident"] == "testcorp"
            assert res["new_career_url"] == "https://jobs.ashbyhq.com/testcorp"


@pytest.mark.anyio
async def test_recover_company_via_candidate_probing():
    client = AsyncMock()
    comp = {
        "company_name": "Cursor",
        "ats_platform": "greenhouse",
        "ats_identifier": "cursor",
        "career_url": "",
    }

    async def mock_verify(client, plat, ident):
        if ident == "anysphere" and plat == "ashby":
            return True, "8 jobs"
        return False, "404"

    with patch("scripts.scan_and_fix_links.verify_ats", side_effect=mock_verify):
        with patch("scripts.scan_and_fix_links.probe_career_url", new=AsyncMock(return_value=None)):
            res = await recover_company(client, comp)
            assert res["status"] == "recovered"
            assert res["new_platform"] == "ashby"
            assert res["new_ident"] == "anysphere"
            assert res["new_career_url"] == "https://jobs.ashbyhq.com/anysphere"


def test_construct_career_url():
    assert construct_career_url("ashby", "consensys") == "https://jobs.ashbyhq.com/consensys"
    assert construct_career_url("greenhouse", "adahealth") == "https://job-boards.greenhouse.io/adahealth"
    assert construct_career_url("lever", "agicap") == "https://jobs.lever.co/agicap"
    assert construct_career_url("workday", "adobe|wd5|external_experienced") == "https://adobe.wd5.myworkdayjobs.com/external_experienced"
    assert construct_career_url("smartrecruiters", "foo") == "https://careers.smartrecruiters.com/foo"
    assert construct_career_url("unknown", "bar") == ""


@pytest.mark.anyio
async def test_recover_company_via_workday_clusters():
    client = AsyncMock()
    comp = {
        "company_name": "Adobe",
        "ats_platform": "workday",
        "ats_identifier": "adobe|wd1|external",
        "career_url": "https://adobe.wd1.myworkdayjobs.com/external",
    }

    async def mock_verify(client, plat, ident):
        if plat == "workday" and ident == "adobe|wd5|external_experienced":
            return True, "25 jobs"
        return False, "404"

    with patch("scripts.scan_and_fix_links.verify_ats", side_effect=mock_verify):
        with patch("scripts.scan_and_fix_links.probe_career_url", new=AsyncMock(return_value=None)):
            with patch("scripts.scan_and_fix_links.probe_workday_clusters", new=AsyncMock(return_value="adobe|wd5|external_experienced")):
                res = await recover_company(client, comp)
                assert res["status"] == "recovered"
                assert res["new_platform"] == "workday"
                assert res["new_ident"] == "adobe|wd5|external_experienced"
                assert res["new_career_url"] == "https://adobe.wd5.myworkdayjobs.com/external_experienced"


