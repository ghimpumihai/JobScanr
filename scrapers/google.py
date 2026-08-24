"""Google careers client.

Google runs no public ATS. Their careers site is server-rendered: one
results page per location contains every listing's title, locations,
experience level (Early/Mid/...) and application link directly in the
HTML. We parse those cards — one polite request per configured location,
no separate API.

Identifier format: pipe-separated location names, matching the site's
?location= parameter, e.g. "Germany|Netherlands|Ireland".
"""

import asyncio
import re

from scrapers.base import BaseClient

BASE = "https://www.google.com/about/careers/applications"
RESULTS_URL = f"{BASE}/jobs/results/"

CARD_RE = re.compile(
    r'href="(?P<path>jobs/results/[0-9A-Za-z_-]+)\?[^"]*"\s+'
    r'aria-label="Learn more about (?P<title>[^"]+)"',
)
PIPE_RE = re.compile(r"<[^>]+>")


def _tokens(window: str) -> list[str]:
    t = PIPE_RE.sub("|", window)
    return [x.strip() for x in t.split("|") if x.strip()]


def parse_card(window: str, path: str, title: str) -> dict | None:
    """Extract locations + experience level from the markup preceding a card's
    link. Uses the CLOSEST place/bar_chart pair so tightly-packed cards don't
    inherit their neighbour's data."""
    toks = _tokens(window[:4000])
    bars = [i for i, t in enumerate(toks) if t == "bar_chart"]
    places = [i for i, t in enumerate(toks) if t == "place"]
    if not bars or not places:
        return None
    end = bars[-1]
    starts_before = [i for i in places if i < end]
    if not starts_before:
        return None
    start = starts_before[-1]
    locations = [t for t in toks[start + 1:end] if not t.startswith("+")]
    level = toks[end + 1] if end + 1 < len(toks) else None
    if not title or not path:
        return None
    return {
        "external_id": path.rsplit("-", 1)[-1][:60] or path,
        "title": title.strip(),
        "location": ", ".join(locations) or None,
        "department": None,
        "url": f"{BASE}/{path}",
        "description": None,
        "ats_identifier": None,
        "google_level": level,
    }


class GoogleClient(BaseClient):
    MAX_PAGES = 6

    async def get_jobs(self, ats_identifier: str) -> list[dict]:
        locations = [x for x in ats_identifier.split("|") if x]
        jobs: dict[str, dict] = {}
        for location in locations:
            prev_ids: set[str] = set()
            for page in range(1, self.MAX_PAGES + 1):
                params = {"location": location}
                if page > 1:
                    params["page"] = str(page)
                r = await self.request_with_retry(
                    "GET", RESULTS_URL, params=params)
                r.raise_for_status()
                html = r.text
                new_on_page = 0
                for m in CARD_RE.finditer(html):
                    path, title = m.group("path"), m.group("title")
                    if path in jobs:
                        continue
                    # Card content precedes its "Learn more" link.
                    card = parse_card(html[max(0, m.start() - 4000):m.start()],
                                      path, title)
                    if card is None:
                        continue
                    card["ats_identifier"] = ats_identifier
                    jobs[card["external_id"]] = card
                    new_on_page += 1
                page_ids = set(re.findall(r"jobs/results/([0-9A-Za-z_-]+)\?", html))
                if not new_on_page and not (page_ids - prev_ids):
                    break  # empty or duplicate page = end of results
                prev_ids = page_ids
                await asyncio.sleep(0.8)
            await asyncio.sleep(1.0)  # politeness across location queries
        return list(jobs.values())

