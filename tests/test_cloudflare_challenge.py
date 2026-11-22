import asyncio
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from jobs import scrape_and_notify as sn
from scrapers import base
from scrapers.base import BaseClient, BlockedByChallenge, challenge_tracker


class _Client(BaseClient):
    async def get_jobs(self, ats_identifier):  # pragma: no cover - not used
        return []


@pytest.fixture(autouse=True)
def _reset_tracker():
    challenge_tracker.reset()
    yield
    challenge_tracker.reset()


def _challenge(request: httpx.Request) -> httpx.Response:
    return httpx.Response(429, headers={"cf-mitigated": "challenge"}, text="<html>challenge</html>")


def _run(coro):
    return asyncio.run(coro)


def test_challenge_is_not_retried_or_slept_on():
    calls = []

    def handler(request):
        calls.append(1)
        return _challenge(request)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with patch("scrapers.base.asyncio.sleep", new_callable=AsyncMock) as sleep:
                with pytest.raises(BlockedByChallenge):
                    await _Client(http).request_with_retry(
                        "POST", "https://acme.wd1.myworkdayjobs.com/wday/cxs/a/b/jobs"
                    )
                return sleep.await_count

    assert _run(go()) == 0  # the old behaviour slept ~49.6s across 5 attempts
    assert len(calls) == 1


def test_plain_429_is_still_retried_with_backoff():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={}) if len(calls) == 3 else httpx.Response(429)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with patch("scrapers.base.asyncio.sleep", new_callable=AsyncMock):
                r = await _Client(http).request_with_retry("GET", "https://x.example.com/")
                return r.status_code

    assert _run(go()) == 200
    assert len(calls) == 3  # a 429 without cf-mitigated keeps the retry behaviour


def test_pod_is_skipped_after_consecutive_challenges_and_other_pods_are_unaffected():
    seen = []

    def handler(request):
        seen.append(request.url.host)
        if request.url.host.endswith(".wd1.myworkdayjobs.com"):
            return _challenge(request)
        return httpx.Response(200, json={})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            c = _Client(http)
            for i in range(base.BLOCK_AFTER_CONSECUTIVE + 3):
                with pytest.raises(BlockedByChallenge):
                    await c.request_with_retry("POST", f"https://t{i}.wd1.myworkdayjobs.com/x")
            ok = await c.request_with_retry("POST", "https://t.wd3.myworkdayjobs.com/x")
            return ok.status_code

    assert _run(go()) == 200
    wd1_requests = [h for h in seen if ".wd1." in h]
    assert len(wd1_requests) == base.BLOCK_AFTER_CONSECUTIVE  # later tenants were skipped without any request
    assert any(".wd3." in h for h in seen)


def test_a_success_resets_the_streak():
    state = {"n": 0}

    def handler(request):
        state["n"] += 1
        return httpx.Response(200, json={}) if state["n"] == 3 else _challenge(request)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            c = _Client(http)
            url = "https://t.wd5.myworkdayjobs.com/x"
            for _ in range(2):
                with pytest.raises(BlockedByChallenge):
                    await c.request_with_retry("GET", url)
            await c.request_with_retry("GET", url)  # success
            return challenge_tracker.is_blocked(challenge_tracker.key(url))

    assert _run(go()) is False


def _fake_http():
    @asynccontextmanager
    async def _ctx():
        yield object()

    return _ctx()


def test_scrape_all_reports_blocked_separately_from_failures():
    companies = [
        {"id": 1, "name": "A", "ats_platform": "workday", "ats_identifier": "a|wd1|s"},
        {"id": 2, "name": "B", "ats_platform": "greenhouse", "ats_identifier": "b"},
        {"id": 3, "name": "C", "ats_platform": "lever", "ats_identifier": "c"},
    ]

    async def fake_fetch(http, c):
        if c["ats_platform"] == "workday":
            raise BlockedByChallenge("blocked")
        if c["ats_platform"] == "lever":
            raise RuntimeError("boom")
        return []

    details, blocked = [], []
    with patch.object(sn, "make_http_client", _fake_http), patch.object(sn, "fetch_company", fake_fetch):
        jobs, failures = _run(sn.scrape_all(companies, failure_details=details, blocked=blocked))
    assert [c["name"] for c in blocked] == ["A"]
    assert len(failures) == 1 and "C (lever)" in failures[0]  # only the real failure
    assert {d["company_name"]: d.get("blocked", False) for d in details} == {"A": True, "C": False}


def test_link_fixer_ignores_blocked_entries_and_does_not_fall_back_to_the_log(tmp_path, capsys):
    from argparse import Namespace

    from scripts import scan_and_fix_links as fixer

    companies = tmp_path / "companies.json"
    companies.write_text(
        json.dumps(
            [
                {
                    "company_name": "Blocked Co",
                    "career_url": "https://blocked.wd1.myworkdayjobs.com/site",
                    "ats_platform": "workday",
                    "ats_identifier": "blocked|wd1|site",
                }
            ]
        )
    )
    failures = tmp_path / "failures.json"
    failures.write_text(
        json.dumps(
            [
                {
                    "company_name": "Blocked Co",
                    "ats_platform": "workday",
                    "ats_identifier": "blocked|wd1|site",
                    "error": "challenge",
                    "blocked": True,
                }
            ]
        )
    )
    log = tmp_path / "scrape.log"
    log.write_text("Blocked Co (workday): HTTP 429\n")  # would be parsed as a failure if we fell back to the log
    report = tmp_path / "report.md"
    args = Namespace(
        companies_file=str(companies),
        failures_file=str(failures),
        log_file=str(log),
        report_file=str(report),
        manual_review_file=None,
        ai=False,
        prune=False,
    )
    assert asyncio.run(fixer.main_async(args)) == 0
    out = capsys.readouterr().out
    assert "Ignoring 1 companies blocked" in out and "Nothing to fix" in out
    assert "No failures detected" in report.read_text()
    assert json.loads(companies.read_text())[0]["ats_identifier"] == "blocked|wd1|site"  # untouched


@pytest.mark.parametrize("status", [403, 429, 503])
def test_a_challenge_is_recognised_whatever_its_status(status):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(status, headers={"cf-mitigated": "challenge"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(BlockedByChallenge):
                await _Client(http).request_with_retry("GET", "https://a.wd1.myworkdayjobs.com/x")

    _run(run())
    assert len(calls) == 1
