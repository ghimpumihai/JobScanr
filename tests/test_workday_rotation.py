import asyncio
from contextlib import asynccontextmanager
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from jobs import scrape_and_notify as sn


def _companies(n_workday=20, n_other=5):
    cs = [
        {"id": i, "name": f"W{i}", "ats_platform": "workday", "ats_identifier": f"t{i}|wd1|s"} for i in range(n_workday)
    ]
    cs += [
        {"id": 1000 + i, "name": f"G{i}", "ats_platform": "greenhouse", "ats_identifier": f"g{i}"}
        for i in range(n_other)
    ]
    return cs


def test_rotation_one_returns_everything():
    cs = _companies()
    assert sn.select_companies_for_today(cs, rotation_days=1) == cs


@pytest.mark.parametrize("rotation", [2, 3])
def test_every_workday_company_is_scraped_exactly_once_per_cycle(rotation):
    cs = _companies(n_workday=30)
    start = date(2026, 11, 18)
    seen = []
    for d in range(rotation):
        picked = sn.select_companies_for_today(cs, rotation_days=rotation, today=start + timedelta(days=d))
        # non-Workday companies are never rotated
        assert sum(1 for c in picked if c["ats_platform"] == "greenhouse") == 5
        seen += [c["id"] for c in picked if c["ats_platform"] == "workday"]
    assert sorted(seen) == list(range(30))  # no gaps, no duplicates


def test_company_without_id_is_always_included():
    c = {"id": None, "name": "X", "ats_platform": "workday", "ats_identifier": "t|wd1|s"}
    assert sn.select_companies_for_today([c], rotation_days=3, today=date(2026, 11, 18)) == [c]


def _fake_client():
    @asynccontextmanager
    async def _ctx():
        yield object()

    return _ctx()


def test_deadline_skips_workday_but_not_other_platforms_and_is_not_a_failure():
    cs = _companies(n_workday=4, n_other=3)
    fake = AsyncMock(return_value=[])
    with patch.object(sn, "make_http_client", _fake_client), patch.object(sn, "fetch_company", fake):
        jobs, failures = asyncio.run(sn.scrape_all(cs, workday_deadline=0))
    assert failures == []
    called = {c.args[1]["ats_platform"] for c in fake.call_args_list}
    assert called == {"greenhouse"}  # every Workday company skipped, others still scraped
    assert fake.call_count == 3


def test_no_deadline_scrapes_everything():
    cs = _companies(n_workday=4, n_other=3)
    fake = AsyncMock(return_value=[])
    with patch.object(sn, "make_http_client", _fake_client), patch.object(sn, "fetch_company", fake):
        asyncio.run(sn.scrape_all(cs, workday_deadline=None))
    assert fake.call_count == 7
