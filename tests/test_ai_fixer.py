import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from scripts.ai_fixer import (
    analyze_with_groq,
    construct_career_url,
    detect_unsupported_ats_in_results,
    extract_ats_candidates_from_results,
    triage_company_with_ai,
)
from scripts.scan_and_fix_links import remove_companies_from_seed


def test_extract_ats_candidates_from_results():
    results = [
        {"href": "https://jobs.lever.co/spotify/", "body": "Open roles at Spotify"},
        {"href": "https://jobs.ashbyhq.com/consensys", "body": "ConsenSys careers"},
        {"href": "https://job-boards.greenhouse.io/adahealth", "body": "Ada Health jobs"},
        {"href": "https://adobe.wd5.myworkdayjobs.com/external_experienced", "body": "Adobe careers"},
        {"href": "https://careers.smartrecruiters.com/foo", "body": "Foo jobs"},
    ]
    candidates = extract_ats_candidates_from_results(results)
    assert ("lever", "spotify", "https://jobs.lever.co/spotify/") in candidates
    assert ("ashby", "consensys", "https://jobs.ashbyhq.com/consensys") in candidates
    assert ("greenhouse", "adahealth", "https://job-boards.greenhouse.io/adahealth") in candidates
    assert ("workday", "adobe|wd5|external_experienced", "https://adobe.wd5.myworkdayjobs.com/external_experienced") in candidates
    assert ("smartrecruiters", "foo", "https://careers.smartrecruiters.com/foo") in candidates


def test_detect_unsupported_ats_in_results():
    results = [
        {"href": "https://company.personio.de/jobs", "body": "Apply via Personio"},
    ]
    assert detect_unsupported_ats_in_results(results) == "personio"

    clean_results = [
        {"href": "https://company.com/about", "body": "About us"},
    ]
    assert detect_unsupported_ats_in_results(clean_results) is None


@pytest.mark.anyio
async def test_analyze_with_groq():
    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": '{"supported_ats_found": true, "platform": "ashby", "identifier": "consensys", "career_url": "https://jobs.ashbyhq.com/consensys", "reason": "verified"}'
                }
            }
        ]
    }

    mock_client = AsyncMock()
    mock_client.post.return_value = fake_resp
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("httpx.AsyncClient", return_value=mock_client):
        parsed = await analyze_with_groq("ConsenSys", [], groq_api_key="fake-key")
        assert parsed is not None
        assert parsed["supported_ats_found"] is True
        assert parsed["platform"] == "ashby"
        assert parsed["identifier"] == "consensys"


@pytest.mark.anyio
async def test_triage_company_with_ai_recovers_live_feed():
    client = AsyncMock()
    company = {
        "company_name": "Acme",
        "ats_platform": "greenhouse",
        "ats_identifier": "acme-old",
        "career_url": "https://boards.greenhouse.io/acme-old",
    }

    fake_search = [
        {"title": "Acme Careers", "href": "https://jobs.ashbyhq.com/acme", "body": "Jobs at Acme"}
    ]

    with patch("scripts.ai_fixer.search_duckduckgo", return_value=fake_search):
        with patch("scripts.ai_fixer.verify_ats", new=AsyncMock(return_value=(True, "10 jobs"))):
            res = await triage_company_with_ai(client, company)
            assert res["status"] == "recovered_by_ai"
            assert res["new_platform"] == "ashby"
            assert res["new_ident"] == "acme"
            assert "10 jobs" in res["verification_detail"]


@pytest.mark.anyio
async def test_triage_company_with_ai_rejects_hallucination():
    client = AsyncMock()
    company = {
        "company_name": "GhostCorp",
        "ats_platform": "lever",
        "ats_identifier": "ghostcorp",
    }

    fake_search = []
    fake_groq = {
        "supported_ats_found": True,
        "platform": "lever",
        "identifier": "ghostcorp-fake",
        "reason": "hallucinated guess",
    }

    with patch("scripts.ai_fixer.search_duckduckgo", return_value=fake_search):
        with patch("scripts.ai_fixer.analyze_with_groq", new=AsyncMock(return_value=fake_groq)):
            # verify_ats fails for the fake identifier
            with patch("scripts.ai_fixer.verify_ats", new=AsyncMock(return_value=(False, "404 Not Found"))):
                res = await triage_company_with_ai(client, company)
                assert res["status"] != "recovered_by_ai"


@pytest.mark.anyio
async def test_triage_company_with_ai_marks_unsupported_for_removal():
    client = AsyncMock()
    company = {
        "company_name": "PersonioUserCorp",
        "ats_platform": "greenhouse",
        "ats_identifier": "personiouser",
    }

    fake_search = [
        {"title": "Jobs at PersonioUserCorp", "href": "https://personiousercorp.personio.de", "body": "Personio jobs"}
    ]
    fake_groq = {
        "supported_ats_found": False,
        "unsupported_ats": "personio",
        "reason": "Company uses Personio careers site",
    }

    with patch("scripts.ai_fixer.search_duckduckgo", return_value=fake_search):
        with patch("scripts.ai_fixer.analyze_with_groq", new=AsyncMock(return_value=fake_groq)):
            with patch("scripts.ai_fixer.verify_ats", new=AsyncMock(return_value=(False, "404"))):
                res = await triage_company_with_ai(client, company)
                assert res["status"] == "remove"
                assert "personio" in res["reason"].lower()


def test_remove_companies_from_seed():
    companies = [
        {"company_name": "KeepMe", "ats_platform": "ashby", "ats_identifier": "keep"},
        {"company_name": "DropMe", "ats_platform": "greenhouse", "ats_identifier": "drop"},
    ]
    to_remove = [
        {"company_name": "DropMe", "old_platform": "greenhouse", "old_ident": "drop"}
    ]
    filtered, count = remove_companies_from_seed(companies, to_remove)
    assert count == 1
    assert len(filtered) == 1
    assert filtered[0]["company_name"] == "KeepMe"

