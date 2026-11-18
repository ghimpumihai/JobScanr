"""Workday request reduction: change detection (A1), early paging stop (A2), country facets (A3),
cached enrichment verdicts (A4). All mock transports, no network."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx

from jobs import scrape_and_notify as sn
from scrapers.base import BlockedByChallenge
from scrapers.workday import WorkdayClient, _country_facets

IDENT = "acme|wd1|Careers"


def _posting(i: int) -> dict:
    return {"jobPostingId": f"R{i}", "title": f"Software Engineer {i}", "externalPath": f"/job/X/SE_R{i}"}


def _board(ids: list[int], page_size: int = 20, facets: list | None = None):
    """Handler serving a board whose postings are ``ids`` (newest first); records each request payload."""
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        off = body["offset"]
        return httpx.Response(
            200,
            json={
                "total": len(ids),
                "jobPostings": [_posting(i) for i in ids[off : off + page_size]],
                "facets": facets or [],
            },
        )

    return handler, calls


def _scan(handler, state=None, countries=None):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                return await WorkdayClient(http).get_jobs(IDENT, state=state, countries=countries)

    return asyncio.run(run())


def _recent(days: int = 1) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def test_unchanged_board_costs_one_request():
    state: dict = {}
    handler, calls = _board(list(range(30)))
    first = _scan(handler, state)
    assert len(calls) == 2 and len(first) == 30  # small board, full scan pages everything

    state["full_scan_at"] = _recent()
    handler, calls = _board(list(range(30)))
    again = _scan(handler, state)
    assert len(calls) == 1
    assert {j["external_id"] for j in again} == {j["external_id"] for j in first}


def test_new_job_on_top_stops_at_first_known_page_and_merges_cache():
    state = {"full_scan_at": _recent()}
    _scan(_board(list(range(1, 31)))[0], state)

    handler, calls = _board([100] + list(range(1, 31)))  # one new job, everything shifts by one
    jobs = _scan(handler, state)
    assert len(calls) == 2  # page 2 is all known, so no page 3
    assert {j["external_id"] for j in jobs} == {f"R{i}" for i in [100, *range(1, 31)]}


def test_full_scan_due_ignores_cache():
    state: dict = {}
    _scan(_board(list(range(30)))[0], state)
    state["full_scan_at"] = _recent(8)
    handler, calls = _board(list(range(30)))
    _scan(handler, state)
    assert len(calls) == 2  # unchanged board, but the weekly full scan pages everything anyway
    assert datetime.fromisoformat(state["full_scan_at"]) > datetime.now(timezone.utc) - timedelta(minutes=1)


def test_first_full_scan_is_staggered_within_a_week():
    state: dict = {}
    _scan(_board([1])[0], state)
    age = datetime.now(timezone.utc) - datetime.fromisoformat(state["full_scan_at"])
    assert timedelta(0) <= age < timedelta(days=7)


def test_failed_scan_leaves_state_untouched():
    state = {"queries": {"x": 1}, "full_scan_at": _recent()}

    def handler(request):
        return httpx.Response(429, headers={"cf-mitigated": "challenge"})

    try:
        _scan(handler, state)
    except BlockedByChallenge:
        pass
    assert state == {"queries": {"x": 1}, "full_scan_at": state["full_scan_at"]}


COUNTRY_FACETS = [
    {
        "facetParameter": "locationMainGroup",
        "values": [
            {
                "facetParameter": "locationCountry",
                "values": [
                    {"descriptor": "Germany", "id": "g-de", "count": 3},
                    {"descriptor": "United States of America", "id": "g-us", "count": 90},
                ],
            }
        ],
    }
]


def test_country_facet_found_in_nested_facets():
    assert _country_facets(COUNTRY_FACETS, {"germany", "france"}) == {"locationCountry": ["g-de"]}
    assert _country_facets(COUNTRY_FACETS, {"france"}) == {}
    assert _country_facets(None, {"germany"}) == {}


def test_large_board_queries_carry_country_facet():
    handler, calls = _board(list(range(60)), facets=COUNTRY_FACETS)
    _scan(handler, {}, countries={"germany"})
    searches = [c for c in calls if c["searchText"]]
    assert searches and all(c["appliedFacets"] == {"locationCountry": ["g-de"]} for c in searches)


def test_large_board_without_matching_facet_falls_back_to_keywords():
    handler, calls = _board(list(range(60)), facets=COUNTRY_FACETS)
    _scan(handler, {}, countries={"france"})
    assert all(c["appliedFacets"] == {} for c in calls)


# A4: cached per-profile verdicts


def _job(**kw) -> dict:
    return {"ats_platform": "workday", "company_id": 1, "external_id": "R1", "description": None, **kw}


def test_cache_hit_reuses_verdict_and_fields():
    states = {1: {"enrichment": {"R1": {"at": _recent(), "verdicts": {"h1": True}, "location": "Berlin"}}}}
    job = _job(location="2 Locations")
    assert sn._apply_cached_enrichment(job, states, {"h1"})
    assert job["location"] == "Berlin"
    assert sn._match(job, {}, "h1") is True


def test_cache_miss_for_new_profile_stale_entry_or_other_platform():
    states = {1: {"enrichment": {"R1": {"at": _recent(), "verdicts": {"h1": True}}}}}
    assert not sn._apply_cached_enrichment(_job(), states, {"h1", "h2"})  # a profile without a verdict
    states[1]["enrichment"]["R1"]["at"] = _recent(8)
    assert not sn._apply_cached_enrichment(_job(), states, {"h1"})  # expired
    assert not sn._apply_cached_enrichment(_job(ats_platform="ashby"), states, {"h1"})


def test_only_verdicts_made_with_a_description_are_recorded():
    states: dict[int, dict] = {1: {"enrichment": {"GONE": {"at": _recent()}}}}
    with patch.object(sn, "matches_profile", return_value=False):
        enriched = _job(external_id="R1", description="text")
        failed_fetch = _job(external_id="R2")
        sn._match(enriched, {}, "h1")
        sn._match(failed_fetch, {}, "h1")
    sn._record_enrichment([enriched, failed_fetch], states)
    cache = states[1]["enrichment"]
    assert cache["R1"]["verdicts"] == {"h1": False}
    assert "R2" not in cache  # no description, nothing worth caching
    assert "GONE" not in cache  # no longer listed


def test_facet_countries_layers_each_user_over_the_default_profile():
    p = {"locations": ["Berlin"], "eligible_regions": ["Germany"]}
    assert sn._facet_countries([{"profile_filters": p}], p) == {"berlin", "germany"}
    # A user without eligible_regions inherits the default's, exactly as the matcher sees them.
    paris = {"profile_filters": {"locations": ["Paris"]}}
    assert sn._facet_countries([{"profile_filters": p}, paris], p) == {"berlin", "germany", "paris"}
    # No eligible_regions anywhere: city-only locations can't be mapped to countries, so don't narrow.
    assert sn._facet_countries([paris], {"locations": ["Paris"]}) is None


def test_challenged_detail_fetch_is_not_retried():
    from jobs.enrich import _fetch_detail
    from scrapers.base import challenge_tracker

    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, headers={"cf-mitigated": "challenge"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with patch("asyncio.sleep", new_callable=AsyncMock) as sleep:
                out = await _fetch_detail(_job(ats_identifier=IDENT, external_path="SE_R1"), http)
                return out, sleep

    challenge_tracker.reset()
    try:
        out, sleep = asyncio.run(run())
    finally:
        challenge_tracker.reset()
    assert out is None and len(calls) == 1 and not sleep.called
