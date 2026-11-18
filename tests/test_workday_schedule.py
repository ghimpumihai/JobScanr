"""Workday scheduling and politeness: tiered schedule (A5), per-pod pacing (B6), persisted back-off (B9)."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from jobs import scrape_and_notify as sn
from scrapers import workday as workday_module
from scrapers.base import BaseClient, BlockedByChallenge, challenge_tracker
from scrapers.workday import WorkdayClient, is_hot

POD = "wd1.myworkdayjobs.com"


@pytest.fixture(autouse=True)
def _reset_tracker():
    challenge_tracker.reset()
    yield
    challenge_tracker.reset()


def _ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _company(cid: int, tenant: str) -> dict:
    return {"id": cid, "name": tenant, "ats_platform": "workday", "ats_identifier": f"{tenant}|wd1|Careers"}


def _cached(full_scan_days: float, candidate_days: float | None = None) -> dict:
    posting = {"jobPostingId": "R1", "title": "Software Engineer", "externalPath": "/job/X/SE_R1"}
    return {
        "queries": {json.dumps(["", {}]): {"total": 1, "first_ids": ["/job/X/SE_R1"], "postings": [posting]}},
        "full_scan_at": _ago(full_scan_days),
        "last_candidate_at": _ago(candidate_days) if candidate_days is not None else None,
    }


def _scrape(companies, states, handler):
    def client():
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def run():
        with patch.object(sn, "make_http_client", client), patch("asyncio.sleep", new_callable=AsyncMock):
            blocked: list = []
            jobs, failures = await sn.scrape_all(companies, blocked=blocked, workday_states=states)
            return jobs, failures, blocked

    return asyncio.run(run())


def _recording(response):
    hosts: list[str] = []

    def handler(request):
        hosts.append(request.url.host)
        return response(request)

    return handler, hosts


def _ok(request):
    return httpx.Response(200, json={"total": 1, "jobPostings": [{"jobPostingId": "R2", "externalPath": "/job/Y"}]})


def _challenge(request):
    return httpx.Response(429, headers={"cf-mitigated": "challenge"})


# A5: tiered schedule


def test_is_hot():
    assert is_hot({"last_candidate_at": _ago(1)})
    assert not is_hot({"last_candidate_at": _ago(29)})
    assert not is_hot({}) and not is_hot(None)


def test_cold_board_is_served_from_cache_hot_and_due_boards_are_scanned():
    states = {
        1: _cached(full_scan_days=1),  # cold, full scan not due -> cache, no request
        2: _cached(full_scan_days=1, candidate_days=3),  # hot -> scanned
        3: _cached(full_scan_days=8),  # cold but weekly full scan due -> scanned
        4: {},  # never scanned -> scanned
    }
    companies = [_company(1, "cold"), _company(2, "hot"), _company(3, "due"), _company(4, "new")]
    handler, hosts = _recording(_ok)
    jobs, failures, _ = _scrape(companies, states, handler)
    assert not failures
    assert {h.split(".")[0] for h in hosts} == {"hot", "due", "new"}
    assert {j["company_id"] for j in jobs} == {1, 2, 3, 4}
    assert next(j for j in jobs if j["company_id"] == 1)["external_id"] == "R1"


def test_blocked_board_falls_back_to_a_fresh_cache_only():
    states = {1: _cached(full_scan_days=1, candidate_days=1), 2: _cached(full_scan_days=31, candidate_days=1)}
    jobs, failures, blocked = _scrape([_company(1, "fresh"), _company(2, "old")], states, _challenge)
    assert not failures and len(blocked) == 2
    assert {j["company_id"] for j in jobs} == {1}


# B6: per-pod pacing


def test_request_starts_are_spaced_per_pod_not_across_pods():
    class _Http:
        async def request(self, method, url, **kw):
            return httpx.Response(200)

    async def run():
        with patch("asyncio.sleep", new_callable=AsyncMock) as sleep:
            c = WorkdayClient(_Http())  # type: ignore[arg-type]
            for host in ("a.wd1", "b.wd1", "c.wd1", "a.wd5"):
                await c.request_with_retry("GET", f"https://{host}.myworkdayjobs.com/x")
            return [round(call.args[0]) for call in sleep.call_args_list]

    # wd1: 2nd request waits ~1 s, 3rd ~2 s (sleep is mocked, so the clock doesn't move); wd5 doesn't wait
    assert asyncio.run(run()) == [1, 2]


def test_blocked_pod_neither_waits_nor_counts_as_sent():
    challenge_tracker.block(POD)
    WorkdayClient.requests_sent = 0

    async def run():
        with patch("asyncio.sleep", new_callable=AsyncMock) as sleep:
            with pytest.raises(BlockedByChallenge):
                await WorkdayClient(None).request_with_retry("GET", f"https://a.{POD}/x")  # type: ignore[arg-type]
            return sleep

    assert not asyncio.run(run()).called
    assert WorkdayClient.requests_sent == 0


# B9: persisted back-off


class _Client(BaseClient):
    async def get_jobs(self, ats_identifier):  # pragma: no cover - not used
        return []


def test_primed_pod_is_blocked_by_a_single_challenge():
    challenge_tracker.prime(POD)
    calls = []

    def handler(request):
        calls.append(1)
        return _challenge(request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            for _ in range(3):
                with pytest.raises(BlockedByChallenge):
                    await _Client(http).request_with_retry("GET", f"https://a.{POD}/x")

    asyncio.run(run())
    assert len(calls) == 1 and challenge_tracker.is_blocked(POD)


def test_plan_backoff_starts_doubles_caps_and_clears():
    now = datetime.now(timezone.utc)
    up, down = sn._plan_backoff({}, {POD, "boards.greenhouse.io"}, set(), now)
    assert up == {POD: {"until": now + timedelta(days=2), "days": 2}} and not down  # non-Workday hosts ignored

    up, _ = sn._plan_backoff({POD: {"until": now, "days": 2}}, {POD}, set(), now)
    assert up[POD]["days"] == 4
    up, _ = sn._plan_backoff({POD: {"until": now, "days": 8}}, {POD}, set(), now)
    assert up[POD]["days"] == 14

    up, down = sn._plan_backoff({POD: {"until": now, "days": 4}}, set(), {POD}, now)
    assert not up and down == {POD}  # the probe got through


def test_aborted_run_still_saves_pod_backoff():
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    args = SimpleNamespace(profile=None, dry_run=False, failures_file=None)
    companies = [_company(i, f"c{i}") for i in range(12)]

    async def scrape(cs, failure_details=None, blocked=None, workday_states=None, countries=None):
        challenge_tracker.prime(POD)
        challenge_tracker.record_block(POD)  # the pod blocked us during the scan
        blocked.append(cs[0])
        return [], [f"c{i} (workday): 422" for i in range(3)]  # 3 failures out of 11 attempted -> abort

    save = MagicMock()
    with (
        patch("db.queries.get_all_companies", return_value=companies),
        patch("db.queries.get_active_users", return_value=[]),
        patch("db.queries.get_workday_board_states", return_value={}),
        patch("db.queries.get_workday_pod_backoff", return_value={}),
        patch("db.queries.save_workday_board_states"),
        patch("db.queries.save_workday_pod_backoff", save),
        patch.object(sn, "scrape_all", scrape),
    ):
        assert asyncio.run(sn.run_pipeline(args)) == 1
    upserts, _ = save.call_args.args
    assert upserts[POD]["days"] == 2


def test_small_pod_that_only_challenged_is_backed_off_and_tiny_samples_dont_abort():
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    args = SimpleNamespace(profile=None, dry_run=False, failures_file=None)
    small = "wd12.myworkdayjobs.com"

    async def scrape(cs, failure_details=None, blocked=None, workday_states=None, countries=None):
        challenge_tracker.record_block(small)  # one challenge, far below the consecutive limit
        blocked.append(cs[0])
        return [], ["b (workday): 422"]  # 1 failure out of 1 attempted: too few to judge

    save = MagicMock()
    with (
        patch("db.queries.get_all_companies", return_value=[_company(1, "a"), _company(2, "b")]),
        patch("db.queries.get_active_users", return_value=[]),
        patch("db.queries.get_workday_board_states", return_value={}),
        patch("db.queries.get_workday_pod_backoff", return_value={}),
        patch("db.queries.save_workday_board_states"),
        patch("db.queries.save_workday_pod_backoff", save),
        patch("db.queries.upsert_jobs", return_value=[]),
        patch("db.queries.delete_stale_jobs", return_value=0),
        patch("jobs.notify.email_configured", return_value=False),
        patch.object(sn, "scrape_all", scrape),
    ):
        sn_ret = asyncio.run(sn.run_pipeline(args))
    assert sn_ret == 1  # only because no mail channel is configured in this test, not the failure-rate abort
    upserts, _ = save.call_args.args
    assert small in upserts


def test_queued_requests_skip_their_slot_once_the_pod_is_blocked():
    """Production run: 683 wd1 boards queued at the start each waited out a 1 s slot after wd1 was blocked."""
    sent = []

    async def handler(request):
        sent.append(1)
        await asyncio.sleep(0.01)  # a real network yields, so the other requests are already queued
        return _challenge(request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            c = WorkdayClient(http)
            return await asyncio.gather(
                *(c.request_with_retry("GET", f"https://t{i}.{POD}/x") for i in range(20)), return_exceptions=True
            )

    challenge_tracker.prime(POD)  # the first challenge blocks the pod
    WorkdayClient.requests_sent = 0
    loop = asyncio.new_event_loop()
    try:
        with patch.object(workday_module, "POD_INTERVAL", 0.05):
            t0 = loop.time()
            results = loop.run_until_complete(run())
            elapsed = loop.time() - t0
    finally:
        loop.close()
    assert all(isinstance(r, BlockedByChallenge) for r in results)
    assert len(sent) == 1 and WorkdayClient.requests_sent == 1
    assert elapsed < 0.5  # 19 queued slots of 0.05 s would take ~0.95 s
