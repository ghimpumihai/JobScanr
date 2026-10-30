import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scripts.scan_and_fix_links import (
    apply_fixes_to_companies,
    construct_career_url,
    fingerprint_url_and_html,
    generate_candidate_identifiers,
    generate_manual_review_markdown,
    generate_report_markdown,
    parse_failures_from_log,
    recover_company,
    remove_companies_from_seed,
    slugify,
)
from scripts.validate_companies import check_ashby, has_active_jobs


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
        {
            "company_name": "Company A",
            "ats_platform": "greenhouse",
            "ats_identifier": "comp-a-old",
            "career_url": "http://a.com",
        },
        {
            "company_name": "Company B",
            "ats_platform": "lever",
            "ats_identifier": "comp-b",
            "career_url": "http://b.com",
        },
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


def test_apply_fixes_prevents_duplicate_platform_identifier():
    companies = [
        {
            "company_name": "Paradigm",
            "ats_platform": "greenhouse",
            "ats_identifier": "paradigm",
            "career_url": "https://boards.greenhouse.io/paradigm",
        },
        {
            "company_name": "Paradigm",
            "ats_platform": "ashby",
            "ats_identifier": "paradigm",
            "career_url": "https://jobs.ashbyhq.com/paradigm",
        },
    ]
    recoveries = [
        {
            "company_name": "Paradigm",
            "old_platform": "greenhouse",
            "old_ident": "paradigm",
            "status": "recovered",
            "new_platform": "ashby",
            "new_ident": "paradigm",
            "verification_detail": "7 jobs",
        }
    ]

    updated, count = apply_fixes_to_companies(companies, recoveries)
    # Must NOT create a duplicate ('ashby', 'paradigm')
    assert count == 0
    assert recoveries[0]["status"] == "remove"
    assert "pruned duplicate" in recoveries[0]["reason"]

    # When pruned, only the stale greenhouse entry is removed; ashby entry stays intact
    filtered, removed_count = remove_companies_from_seed(updated, recoveries)
    assert removed_count == 1
    assert len(filtered) == 1
    assert filtered[0]["ats_platform"] == "ashby"
    assert filtered[0]["ats_identifier"] == "paradigm"


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


def test_generate_manual_review_markdown():
    recoveries = [
        {
            "company_name": "Recovered Corp",
            "old_platform": "greenhouse",
            "old_ident": "rec-old",
            "status": "recovered",
            "new_platform": "ashby",
            "new_ident": "rec",
            "verification_detail": "10 jobs",
        },
        {
            "company_name": "Transient Inc",
            "old_platform": "lever",
            "old_ident": "transient",
            "status": "transient",
            "reason": "responding",
        },
        {
            "company_name": "Failed With URL",
            "old_platform": "ashby",
            "old_ident": "failed-url",
            "career_url": "https://jobs.ashbyhq.com/failed-url",
            "status": "unrecoverable",
            "reason": "404 not found",
        },
        {
            "company_name": "Failed Without URL",
            "old_platform": "greenhouse",
            "old_ident": "failed-nourl",
            "status": "unresolved",
            "reason": "inconclusive search",
        },
    ]

    md = generate_manual_review_markdown(recoveries)
    assert "# ATS Career Links Needing Manual Review" in md
    assert "| Company | Current ATS | Career Link | Issue |" in md
    assert "| Failed With URL | `ashby/failed-url` | https://jobs.ashbyhq.com/failed-url | 404 not found |" in md
    assert (
        "| Failed Without URL | `greenhouse/failed-nourl` | https://job-boards.greenhouse.io/failed-nourl | inconclusive search |"
        in md
    )
    # Must NOT include fixed or transient logs
    assert "Recovered Corp" not in md
    assert "Transient Inc" not in md
    assert "Summary" not in md
    assert "Verified Fixes" not in md

    # Duplicate unrecoverable entries are deduped
    with_dup = recoveries + [recoveries[2]]
    assert generate_manual_review_markdown(with_dup) == md


def test_generate_manual_review_markdown_empty():
    recoveries = [
        {"company_name": "Company A", "status": "recovered"},
        {"company_name": "Company B", "status": "transient"},
    ]
    assert generate_manual_review_markdown(recoveries) == ""
    assert generate_manual_review_markdown([]) == ""


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
        with patch(
            "scripts.scan_and_fix_links.probe_career_url",
            new=AsyncMock(return_value=("ashby", "testcorp", "https://jobs.ashbyhq.com/testcorp")),
        ):
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
    assert (
        construct_career_url("workday", "adobe|wd5|external_experienced")
        == "https://adobe.wd5.myworkdayjobs.com/external_experienced"
    )
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
            with patch(
                "scripts.scan_and_fix_links.probe_workday_clusters",
                new=AsyncMock(return_value="adobe|wd5|external_experienced"),
            ):
                res = await recover_company(client, comp)
                assert res["status"] == "recovered"
                assert res["new_platform"] == "workday"
                assert res["new_ident"] == "adobe|wd5|external_experienced"
                assert res["new_career_url"] == "https://adobe.wd5.myworkdayjobs.com/external_experienced"


@pytest.mark.anyio
async def test_main_async_ai_prunes_unsupported(tmp_path):
    import argparse

    from scripts.scan_and_fix_links import main_async

    companies_file = tmp_path / "companies.json"
    companies_file.write_text(
        json.dumps(
            [
                {
                    "company_name": "DeadCorp",
                    "ats_platform": "greenhouse",
                    "ats_identifier": "deadcorp",
                    "career_url": "https://boards.greenhouse.io/deadcorp",
                },
                {
                    "company_name": "KeepCorp",
                    "ats_platform": "ashby",
                    "ats_identifier": "keepcorp",
                    "career_url": "https://jobs.ashbyhq.com/keepcorp",
                },
            ]
        )
    )
    failures_file = tmp_path / "failures.json"
    failures_file.write_text(
        json.dumps(
            [
                {
                    "company_name": "DeadCorp",
                    "ats_platform": "greenhouse",
                    "ats_identifier": "deadcorp",
                    "error": "404 Not Found",
                }
            ]
        )
    )
    report_file = tmp_path / "report.md"

    args = argparse.Namespace(
        companies_file=str(companies_file),
        failures_file=str(failures_file),
        log_file=None,
        report_file=str(report_file),
        dry_run=False,
        no_email=True,
        sync_db=False,
        ai=True,
        prune=True,
        max_remove_pct=0.5,
    )

    with patch(
        "scripts.scan_and_fix_links.recover_company",
        new=AsyncMock(
            return_value={
                "company_name": "DeadCorp",
                "old_platform": "greenhouse",
                "old_ident": "deadcorp",
                "career_url": "https://boards.greenhouse.io/deadcorp",
                "status": "unrecoverable",
                "reason": "no live ATS coordinates",
            }
        ),
    ):
        with patch(
            "scripts.ai_fixer.triage_company_with_ai",
            new=AsyncMock(
                return_value={
                    "company_name": "DeadCorp",
                    "old_platform": "greenhouse",
                    "old_ident": "deadcorp",
                    "career_url": "https://boards.greenhouse.io/deadcorp",
                    "status": "remove",
                    "reason": "uses unsupported ATS (personio)",
                }
            ),
        ):
            code = await main_async(args)
            assert code == 0
            # Check companies.json had DeadCorp pruned
            remaining = json.loads(companies_file.read_text())
            assert len(remaining) == 1
            assert remaining[0]["company_name"] == "KeepCorp"

            # Check report content
            report_text = report_file.read_text()
            assert "## Removed Companies" in report_text
            assert "DeadCorp" in report_text
            assert "personio" in report_text


def test_generate_report_markdown_ai_and_removal():
    recoveries = [
        {
            "company_name": "FixedDet",
            "old_platform": "greenhouse",
            "old_ident": "old1",
            "new_platform": "lever",
            "new_ident": "new1",
            "status": "recovered",
            "verification_detail": "5 jobs",
            "reason": "slug candidate",
        },
        {
            "company_name": "FixedAI",
            "old_platform": "ashby",
            "old_ident": "old2",
            "new_platform": "workday",
            "new_ident": "w1|wd2|site",
            "status": "recovered_by_ai",
            "verification_detail": "12 jobs",
            "reason": "search hit",
        },
        {
            "company_name": "PrunedComp",
            "old_platform": "greenhouse",
            "old_ident": "old3",
            "status": "remove",
            "reason": "uses Personio",
        },
    ]
    report = generate_report_markdown(recoveries, 3)
    assert "Successfully Verified & Fixed**: 2 (Deterministic: 1, AI: 1)" in report
    assert "Pruned from Seed (No Supported ATS)**: 1" in report
    assert "## Verified Fixes (Deterministic)" in report
    assert "FixedDet" in report
    assert "## Verified Fixes (AI-Discovered)" in report
    assert "FixedAI" in report
    assert "## Removed Companies (Pruned from `seed/companies.json`)" in report
    assert "PrunedComp" in report


@pytest.mark.anyio
async def test_main_async_preserves_unicode_characters(tmp_path):
    import argparse

    from scripts.scan_and_fix_links import main_async

    companies_file = tmp_path / "companies.json"
    companies_file.write_text(
        json.dumps(
            [
                {
                    "company_name": "AtkinsRéalis",
                    "career_url": "https://slihrms.wd3.myworkdayjobs.com/careers",
                    "ats_platform": "workday",
                    "ats_identifier": "slihrms|wd3|careers",
                },
                {
                    "company_name": "BrokenCorp",
                    "career_url": "https://boards.greenhouse.io/broken",
                    "ats_platform": "greenhouse",
                    "ats_identifier": "broken",
                },
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    failures_file = tmp_path / "failures.json"
    failures_file.write_text(
        json.dumps(
            [
                {
                    "company_name": "BrokenCorp",
                    "ats_platform": "greenhouse",
                    "ats_identifier": "broken",
                    "error": "404 Not Found",
                }
            ]
        ),
        encoding="utf-8",
    )
    report_file = tmp_path / "report.md"

    args = argparse.Namespace(
        companies_file=str(companies_file),
        failures_file=str(failures_file),
        log_file=None,
        report_file=str(report_file),
        dry_run=False,
        no_email=True,
        sync_db=False,
        ai=False,
        prune=False,
    )

    with patch(
        "scripts.scan_and_fix_links.recover_company",
        new=AsyncMock(
            return_value={
                "company_name": "BrokenCorp",
                "old_platform": "greenhouse",
                "old_ident": "broken",
                "status": "recovered",
                "new_platform": "lever",
                "new_ident": "brokenfixed",
                "new_career_url": "https://jobs.lever.co/brokenfixed",
                "verification_detail": "1 job",
            }
        ),
    ):
        code = await main_async(args)
        assert code == 0

        raw_content = companies_file.read_text(encoding="utf-8")
        assert "AtkinsRéalis" in raw_content
        assert "\\u00e9" not in raw_content


def test_has_active_jobs():
    assert has_active_jobs("0 jobs") is False
    assert has_active_jobs("0 cards on first page") is False
    assert has_active_jobs("1 jobs") is True
    assert has_active_jobs("10 jobs") is True
    assert has_active_jobs("374 jobs") is True
    assert has_active_jobs("12 cards on first page") is True
    assert has_active_jobs(None) is False
    assert has_active_jobs("") is False
    assert has_active_jobs("404 Not Found") is False
    assert has_active_jobs("? jobs") is False


@pytest.mark.anyio
async def test_recover_company_step2_self_recovery_marked_as_transient():
    client = AsyncMock()
    comp = {
        "company_name": "GenMD",
        "ats_platform": "ashby",
        "ats_identifier": "genmd",
        "career_url": "https://jobs.ashbyhq.com/genmd",
    }

    # Step 1 fails (e.g. transient timeout or rate limit)
    async def mock_verify(client, plat, ident):
        if plat == "ashby" and ident == "genmd":
            return True, "1 jobs"
        return False, "404"

    with patch("scripts.scan_and_fix_links.verify_ats", side_effect=[(False, "throttled"), (True, "1 jobs")]):
        with patch(
            "scripts.scan_and_fix_links.probe_career_url",
            new=AsyncMock(return_value=("ashby", "genmd", "https://jobs.ashbyhq.com/genmd")),
        ):
            res = await recover_company(client, comp)
            # Must NOT mark as recovered with the same coordinates
            assert res["status"] == "transient"
            assert "old endpoint responding" in res["reason"]


@pytest.mark.anyio
async def test_recover_company_rejects_zero_job_candidate():
    client = AsyncMock()
    comp = {
        "company_name": "Wayve",
        "ats_platform": "greenhouse",
        "ats_identifier": "wayve",
        "career_url": "",
    }

    # Ashby candidate returns 200 OK with 0 jobs
    async def mock_verify(client, plat, ident):
        if plat == "greenhouse" and ident == "wayve":
            return False, "404"
        if plat == "ashby" and ident == "wayve":
            return True, "0 jobs"
        return False, "404"

    with patch("scripts.scan_and_fix_links.verify_ats", side_effect=mock_verify):
        with patch("scripts.scan_and_fix_links.probe_career_url", new=AsyncMock(return_value=None)):
            res = await recover_company(client, comp)
            # 0-job candidate must NOT be accepted as a recovery
            assert res["status"] == "unrecoverable"


@pytest.mark.anyio
async def test_recover_company_rejects_vendor_self_board_and_implausible():
    client = AsyncMock()
    comp = {
        "company_name": "Sunday Robotics",
        "ats_platform": "ashby",
        "ats_identifier": "sunday",
        "career_url": "https://workday.wd5.myworkdayjobs.com/Workday",
    }

    with patch(
        "scripts.scan_and_fix_links.probe_career_url",
        new=AsyncMock(return_value=("workday", "workday|wd5|Workday", "https://workday.wd5.myworkdayjobs.com/Workday")),
    ):
        with patch("scripts.scan_and_fix_links.verify_ats", new=AsyncMock(return_value=(True, "374 jobs"))):
            res = await recover_company(client, comp)
            # Must NOT recover to Workday's self-board
            assert res["status"] != "recovered"
            assert res["new_ident"] != "workday|wd5|Workday"


@pytest.mark.anyio
async def test_recover_company_workday_cluster_self_recovery_marked_as_transient():
    client = AsyncMock()
    comp = {
        "company_name": "Adobe",
        "ats_platform": "workday",
        "ats_identifier": "adobe|wd5|external_experienced",
        "career_url": "https://adobe.wd5.myworkdayjobs.com/external_experienced",
    }

    attempts = 0

    async def mock_verify(client, plat, ident):
        nonlocal attempts
        attempts += 1
        if plat == "workday" and ident == "adobe|wd5|external_experienced":
            if attempts > 1:
                return True, "25 jobs"
        return False, "500"

    with patch("scripts.scan_and_fix_links.verify_ats", side_effect=mock_verify):
        with patch("scripts.scan_and_fix_links.probe_career_url", new=AsyncMock(return_value=None)):
            with patch(
                "scripts.scan_and_fix_links.probe_workday_clusters",
                new=AsyncMock(return_value="adobe|wd5|external_experienced"),
            ):
                res = await recover_company(client, comp)
                assert res["status"] == "transient"
                assert "old workday cluster responding" in res["reason"]


@pytest.mark.anyio
async def test_check_ashby_missing_board_returns_immediately_without_retries():
    client = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": {"jobBoard": None}}
    client.post.return_value = mock_response

    ok, detail = await check_ashby(client, "nonexistent-ident")
    assert ok is False
    assert detail == "board not found"
    assert client.post.call_count == 1
