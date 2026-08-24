"""Discover Workday career-board coordinates for candidate companies.

For each candidate tenant name, scans wd1..wd6 subdomains. The board root
redirects to its real site path (e.g. /en-US/NVIDIAExternalCareerSite),
which is everything the CXS API needs. Verifies each hit with a live
POST /wday/cxs/.../jobs call.

Usage: python -m scripts.discover_workday
"""

import asyncio
import json
import re
import sys

import httpx

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
WD_NUMBERS = [5, 3, 4, 2, 6, 1]
CONCURRENCY = 8

CANDIDATES = [
    "netflix", "salesforce", "klarna", "zalando", "deliveryhero",
    "atlassian", "adobe", "booking", "airbus", "huggingface",
    "revolut", "ocado", "asos", "king", "ubisoft", "riotgames",
    "intel", "cisco", "nokia", "ericsson", "capgemini", "vmware",
    "wayfair", "instacart", "doordash", "lyft",
]

LOCALE_RE = re.compile(r"^/[a-z]{2}-[A-Z]{2}")


async def discover(client: httpx.AsyncClient, tenant: str) -> dict | None:
    for wd in WD_NUMBERS:
        host = f"https://{tenant}.wd{wd}.myworkdayjobs.com"
        try:
            r = await client.get(f"{host}/robots.txt")
        except httpx.HTTPError:
            continue  # no such tenant on this wd number
        # Real boards expose: Sitemap: https://{host}/{Site}/siteMap.xml
        m = re.search(r"Sitemap:\s*\S+?/([^/]+)/siteMap\.xml", r.text or "")
        if not m:
            continue
        site = m.group(1)
        body = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}
        try:
            v = await client.post(f"{host}/wday/cxs/{tenant}/{site}/jobs",
                                  json=body, follow_redirects=True)
        except httpx.HTTPError:
            continue
        if v.status_code != 200:
            continue
        data = v.json()
        postings = data.get("jobPostings")
        if postings is None:
            continue
        return {"company_name": tenant, "wd": wd, "site": site,
                "total_jobs": data.get("total")}
    return None


async def main() -> int:
    sem = asyncio.Semaphore(CONCURRENCY)

    async def bounded(client, tenant):
        async with sem:
            return tenant, await discover(client, tenant)

    async with httpx.AsyncClient(headers=UA, timeout=15.0) as client:
        results = await asyncio.gather(*(bounded(client, t) for t in CANDIDATES))

    found = [r for _, r in results if r]
    print(f"Discovered {len(found)}/{len(CANDIDATES)}:", file=sys.stderr)
    for tenant, r in results:
        line = f"  {tenant:<16}"
        line += (f"-> wd{r['wd']} site={r['site']} ({r['total_jobs']} jobs)"
                 if r else "-> not found")
        print(line, file=sys.stderr)

    json.dump(found, sys.stdout, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
