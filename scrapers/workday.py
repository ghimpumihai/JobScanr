"""Workday career-board client (CXS API).

Board coordinates are NOT guessable — each company needs its real
tenant / wd-number / site name (see scripts/discover_workday.py).
Stored in companies.ats_identifier as "tenant|wdN|SiteName".

Quirks (documented community-wide):
- list endpoint is POST with limit capped at exactly 20 (higher silently
  returns an empty array, looking like end-of-results)
- fast paging trips throttling that also looks like empty results —
  pages are therefore retried before being trusted as exhausted
- listings carry no descriptions; jobs/enrich.py fetches them via the
  detail endpoint using each posting's external_path
"""

import asyncio
import json
import logging
import weakref
import zlib
from datetime import datetime, timedelta, timezone

import httpx

from models import JobPosting
from scrapers.base import BaseClient, BlockedByChallenge, challenge_tracker

logger = logging.getLogger(__name__)

PAGE_SIZE = 20
MAX_PAGES = 100
MAX_SEARCH_PAGES = 5  # For large boards (>40 jobs), cap search pagination to 5 pages per query
SEARCH_QUERIES = ["software", "developer"]
RETRY_DELAY = 2.0
POD_INTERVAL = 1.0  # seconds between request starts on one pod (wd1, wd5, ...): what the challenge reacts to
HOT_FOR = timedelta(days=28)  # a board that produced a candidate this recently is scanned every run
FULL_SCAN_EVERY = timedelta(days=7)  # catches what change detection can miss (an add plus a removal below page 1)


def _slim(p: dict) -> dict:
    """The listing fields we use; this is what gets cached (never descriptions)."""
    return {
        "jobPostingId": p.get("jobPostingId"),
        "title": p.get("title"),
        "externalPath": p.get("externalPath") or "",
        "locationsText": p.get("locationsText"),
    }


class _PodPacer:
    """Spaces request starts per pod by POD_INTERVAL. One per event loop (asyncio locks are loop-bound)."""

    def __init__(self) -> None:
        self._lock: dict[str, asyncio.Lock] = {}
        self._next: dict[str, float] = {}

    async def wait(self, pod: str) -> None:
        async with self._lock.setdefault(pod, asyncio.Lock()):
            now = asyncio.get_running_loop().time()
            start = max(now, self._next.get(pod, now))
            self._next[pod] = start + POD_INTERVAL
            if start > now:
                await asyncio.sleep(start - now)


_pacers: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, _PodPacer]" = weakref.WeakKeyDictionary()


def _pacer() -> _PodPacer:
    return _pacers.setdefault(asyncio.get_running_loop(), _PodPacer())


def is_hot(state: dict | None) -> bool:
    last = (state or {}).get("last_candidate_at")
    return last is not None and datetime.now(timezone.utc) - datetime.fromisoformat(last) < HOT_FOR


def full_scan_due(state: dict | None) -> bool:
    last = (state or {}).get("full_scan_at")
    if not last:
        return True
    return datetime.now(timezone.utc) - datetime.fromisoformat(last) >= FULL_SCAN_EVERY


def _country_facets(facets: list | None, countries: set[str]) -> dict:
    """{facetParameter: [ids]} for the first country facet with values in ``countries``, else {}.

    Facet ids are per-tenant opaque GUIDs, so values are matched on their descriptor. Some tenants
    nest facets (e.g. locationMainGroup -> locationCountry), hence the walk.
    """
    stack = list(facets or [])
    while stack:
        f = stack.pop(0)
        if not isinstance(f, dict):
            continue
        values = f.get("values") or []
        param = f.get("facetParameter") or ""
        if "country" in param.lower():
            ids = [
                v["id"]
                for v in values
                if isinstance(v, dict) and v.get("id") and (v.get("descriptor") or "").strip().lower() in countries
            ]
            if ids:
                return {param: ids}
        stack.extend(v for v in values if isinstance(v, dict) and "facetParameter" in v)
    return {}


class WorkdayClient(BaseClient):
    requests_sent = 0  # process-wide count of Workday requests, for the run log

    def __init__(self, client: httpx.AsyncClient):
        super().__init__(client)

    @staticmethod
    def _base(identifier: str) -> tuple[str, str]:
        tenant, wd, site = identifier.split("|")
        return f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}", tenant

    @staticmethod
    def _public_url(identifier: str, external_path: str) -> str:
        """Human-facing careers page, constructible straight from the listing —
        never depend on the flaky detail fetch for links."""
        tenant, wd, site = identifier.split("|")
        path = external_path if external_path.startswith("/") else f"/{external_path}"
        return f"https://{tenant}.{wd}.myworkdayjobs.com/{site}{path}"

    async def request_with_retry(self, method: str, url: str, **kwargs):
        pod = challenge_tracker.key(url)
        if not challenge_tracker.is_blocked(pod):  # a blocked pod fails at once, it shouldn't queue for pacing
            await _pacer().wait(pod)
            WorkdayClient.requests_sent += 1
        return await super().request_with_retry(method, url, **kwargs)

    @classmethod
    def cached_jobs(cls, ats_identifier: str, state: dict | None) -> list[JobPosting]:
        """The board's jobs from its last scan, without a request."""
        return cls._jobs_from_queries(ats_identifier, (state or {}).get("queries") or {})

    async def get_jobs(
        self, ats_identifier: str, state: dict | None = None, countries: set[str] | None = None
    ) -> list[JobPosting]:
        """List a board's jobs.

        ``state`` is this board's cached scan (workday_board_state.queries/full_scan_at). It is read for
        change detection and updated in place only when the scan succeeds. ``countries`` are lowercase
        country names. When given, large boards are narrowed with the tenant's country facet.
        """
        base, _ = self._base(ats_identifier)
        headers = {"Accept": "application/json"}
        prior: dict = (state or {}).get("queries") or {}
        full = full_scan_due(state)
        new_queries: dict[str, dict] = {}

        async def page(search: str, facets: dict, offset: int) -> dict:
            r = await self.request_with_retry(
                "POST",
                f"{base}/jobs",
                json={"appliedFacets": facets, "limit": PAGE_SIZE, "offset": offset, "searchText": search},
                headers=headers,
            )
            r.raise_for_status()
            return r.json()

        async def run_query(search: str, facets: dict, max_pages: int, first: dict | None = None) -> None:
            key = json.dumps([search, facets], sort_keys=True)
            data = first if first is not None else await page(search, facets, 0)
            total = data.get("total", 0)
            items = [_slim(p) for p in data.get("jobPostings") or []]
            first_ids = [p["externalPath"] for p in items]
            old = None if full else prior.get(key)
            if old and old.get("total") == total and old.get("first_ids") == first_ids:
                rows = old["postings"]  # A1: page 1 unchanged, reuse the cached listing
            else:
                rows = list(items)
                known = {p["externalPath"] for p in old["postings"]} if old else set()
                offset, pages = len(items), 1
                # A2: stop at a page with no new jobs and merge in the cached rows.
                # shortcut: jobs removed below that page linger in the cache until the weekly full scan.
                while not (known and all(p["externalPath"] in known for p in items)):
                    if not items or offset >= total or pages >= max_pages:
                        break
                    await asyncio.sleep(0.4)
                    items = [_slim(p) for p in (await page(search, facets, offset)).get("jobPostings") or []]
                    rows += items
                    offset += len(items)
                    pages += 1
                else:
                    rows += old["postings"] if old else []
                rows = list({p["externalPath"]: p for p in rows}.values())
            new_queries[key] = {"total": total, "first_ids": first_ids, "postings": rows}

        first = await page("", {}, 0)
        unfiltered = json.dumps(["", {}], sort_keys=True)
        sig = {
            "total": first.get("total", 0),
            "first_ids": [_slim(p)["externalPath"] for p in first.get("jobPostings") or []],
        }
        old_sig = prior.get(unfiltered) or {}
        if not full and {"total": old_sig.get("total"), "first_ids": old_sig.get("first_ids")} == sig:
            new_queries = prior  # A1: whole board unchanged since the last scan, 1 request
        elif sig["total"] <= 40:
            # small board: page through everything unfiltered
            await run_query("", {}, MAX_PAGES, first)
        else:
            # large board: the unfiltered page 1 is only the change signature; jobs come from targeted queries
            new_queries[unfiltered] = {**sig, "postings": []}
            facets = _country_facets(first.get("facets"), countries) if countries else {}
            for q in SEARCH_QUERIES:
                await asyncio.sleep(0.4)
                await run_query(q, facets, MAX_SEARCH_PAGES)

        if state is not None:
            state["queries"] = new_queries
            if full:
                now = datetime.now(timezone.utc)
                if not state.get("full_scan_at"):
                    # first scan: spread boards over the week so full scans don't all come due on one day
                    now -= timedelta(days=zlib.crc32(ats_identifier.encode()) % FULL_SCAN_EVERY.days)
                state["full_scan_at"] = now.isoformat()

        return self._jobs_from_queries(ats_identifier, new_queries)

    @classmethod
    def _jobs_from_queries(cls, ats_identifier: str, queries: dict) -> list[JobPosting]:
        jobs: dict[str, JobPosting] = {}
        for entry in queries.values():
            for p in entry["postings"]:
                slug = p["externalPath"].rsplit("/", 1)[-1]
                if slug and slug not in jobs:
                    jobs[slug] = {
                        "external_id": p.get("jobPostingId") or slug,
                        "title": (p.get("title") or "").strip(),
                        # listings often give vague counts ("2 Locations");
                        # the detail fetch fills the real location later
                        "location": p.get("locationsText"),
                        "department": None,
                        "url": cls._public_url(ats_identifier, p["externalPath"]),
                        "description": None,
                        "ats_identifier": ats_identifier,
                        "external_path": slug,
                    }
        return list(jobs.values())

    async def get_job_detail(self, ats_identifier: str, slug: str) -> dict | None:
        """Full HTML description + human-facing URL for one posting."""
        base, _ = self._base(ats_identifier)
        try:
            r = await self.request_with_retry("GET", f"{base}/job/{slug}", headers={"Accept": "application/json"})
            r.raise_for_status()
            body = r.json()
            info = body.get("jobPostingInfo") or {}
            desc = info.get("jobDescription")

            # Workday tenants serve inconsistent shapes: locations may be
            # dicts with a descriptor or bare strings.
            def descriptor(x):
                if isinstance(x, dict):
                    return x.get("descriptor")
                return x if isinstance(x, str) else None

            loc_parts = [descriptor(info.get("location"))] + [
                descriptor(loc) for loc in (info.get("additionalLocations") or [])
            ]
            named = [x for x in loc_parts if x]

            out = {"descriptionHtml": desc}
            # The CXS /job/ path returns raw JSON; only externalUrl is the
            # human-facing page people can actually apply through.
            if info.get("externalUrl"):
                out["externalUrl"] = info["externalUrl"]
            if named:
                out["locationText"] = ", ".join(named)
            return out
        except BlockedByChallenge:
            raise  # not a flaky detail page: the caller must stop, not retry
        except Exception as exc:
            logger.debug("Failed workday detail fetch for %s/%s: %s", ats_identifier, slug, exc)
            return None


def normalize_description(detail: dict) -> str | None:
    """Shared HTML handling lives in scrapers.base."""
    from scrapers.base import strip_html

    return strip_html(detail.get("descriptionHtml"))
