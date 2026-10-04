"""Discover and qualify Workday career-board coordinates for candidate companies.

For each candidate tenant name:
1. Scans Workday clusters (wd1..wd6, wd12, wd103, etc.).
2. Resolves active site paths from robots.txt sitemaps or allow/disallow directives.
3. Queries CXS API /jobs endpoint for early-career software engineering roles.
4. Validates postings against config.py (PROFILE) via jobs.match.matches_profile.
5. Automatically appends new qualified companies to seed/companies.json and syncs PostgreSQL.

Usage:
  python -m scripts.discover_workday               # auto-discovers, saves to seed, and syncs DB
  python -m scripts.discover_workday --dry-run      # preview without saving or syncing
  python -m scripts.discover_workday --candidates nvidia asml
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DB_ENV
from jobs.match import matches_profile

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}
WD_NUMBERS = [1, 2, 3, 4, 5, 6, 12, 103]
CONCURRENCY = 10
TIMEOUT = 10.0

SEED_FILE = Path(__file__).parent.parent / "seed" / "companies.json"

DEFAULT_CANDIDATES = [
    "nvidia", "asml", "motorolasolutions", "qualcomm", "amd", "accenture",
    "philips", "hp", "siemens", "keysight", "purestorage", "nutanix",
    "f5", "iqvia", "genesys", "ptc", "commvault", "analogdevices",
    "kla", "trimble", "marvell", "boeing", "gresearch", "cboe",
    "zoom", "thales", "cohesity", "abb", "netflix", "klarna",
    "deliveryhero", "atlassian", "booking", "airbus", "revolut",
    "ocado", "asos", "king", "ubisoft", "nokia", "ericsson",
    "capgemini", "vmware", "wayfair", "instacart", "doordash", "lyft",
]


def resolve_company_name(tenant: str, existing_companies: list[dict]) -> str:
    """Resolve display name from existing seed if known, otherwise clean tenant name."""
    clean_tenant = re.sub(r"[^a-z0-9]", "", tenant.lower())
    for comp in existing_companies:
        clean_name = re.sub(r"[^a-z0-9]", "", comp["company_name"].lower())
        if clean_name == clean_tenant:
            return comp["company_name"]
    return tenant.replace("-", " ").replace("_", " ").title()


async def probe_sites(client: httpx.AsyncClient, tenant: str) -> list[tuple[int, str]]:
    """Find all active (wd, site) pairs for a tenant."""
    found = []
    for wd in WD_NUMBERS:
        host = f"https://{tenant}.wd{wd}.myworkdayjobs.com"
        try:
            r = await client.get(f"{host}/robots.txt")
        except Exception:
            continue
        if r.status_code != 200:
            continue

        sites = set(re.findall(r"Sitemap:\s*\S+?/([^/]+)/siteMap\.xml", r.text or ""))
        for d in re.findall(r"(?:Allow|Disallow):\s*/([^/]+)/", r.text or ""):
            d_clean = d.strip()
            if not any(x in d_clean.lower() for x in ["talent", "refresh", "search", "wday", "error", "static"]):
                sites.add(d_clean)

        for site in sites:
            found.append((wd, site))

    return found


async def qualify_workday(
    client: httpx.AsyncClient,
    tenant: str,
    wd: int,
    site: str,
    existing_companies: list[dict],
    early_career_only: bool = True,
) -> tuple[dict, list[dict]] | None:
    """Test if a Workday board has matching early-career or tech jobs.
    
    Returns (company_dict, matched_jobs) where company_dict strictly adheres
    to the seed/companies.json schema.
    """
    url = f"https://{tenant}.wd{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    matched_jobs = []

    queries = ["intern", "graduate", "junior", "software", ""] if early_career_only else ["software", "developer", ""]
    for q in queries:
        try:
            r = await client.post(
                url,
                json={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": q},
            )
            if r.status_code != 200:
                continue
            data = r.json()
            postings = data.get("jobPostings") or []
            for p in postings:
                job = {
                    "title": p.get("title") or "",
                    "location": p.get("locationsText") or "",
                    "description": "",
                }
                if matches_profile(job):
                    matched_jobs.append(job)
        except Exception:
            continue
        if matched_jobs:
            break

    if early_career_only and not matched_jobs:
        return None

    name = resolve_company_name(tenant, existing_companies)

    company_entry = {
        "company_name": name,
        "career_url": f"https://{tenant}.wd{wd}.myworkdayjobs.com/{site}",
        "ats_platform": "workday",
        "ats_identifier": f"{tenant}|wd{wd}|{site}",
    }

    return company_entry, matched_jobs


async def discover_tenant(
    client: httpx.AsyncClient,
    tenant: str,
    existing_companies: list[dict],
    early_career_only: bool = True,
) -> tuple[dict, list[dict]] | None:
    sites = await probe_sites(client, tenant)
    for wd, site in sites:
        res = await qualify_workday(
            client,
            tenant,
            wd,
            site,
            existing_companies,
            early_career_only=early_career_only,
        )
        if res:
            return res
    return None


async def main() -> int:
    parser = argparse.ArgumentParser(description="Discover and qualify Workday career boards.")
    parser.add_argument("--candidates", nargs="*", default=None,
                        help="specific candidate tenant names to probe (default: all curated candidates)")
    parser.add_argument("--all-roles", action="store_true",
                        help="qualify if any software role exists, not strictly early-career")
    parser.add_argument("--dry-run", action="store_true",
                        help="probe and print without writing to disk or database")
    args = parser.parse_args()

    candidates = args.candidates if args.candidates else DEFAULT_CANDIDATES
    existing_companies = json.loads(SEED_FILE.read_text()) if SEED_FILE.is_file() else []
    existing_idents = {c["ats_identifier"] for c in existing_companies}
    existing_names = {c["company_name"].lower() for c in existing_companies}

    print(f"Loaded {len(existing_companies)} existing companies from {SEED_FILE}.")
    print(f"Probing {len(candidates)} candidates on Workday (early-career only: {not args.all_roles})...\n")

    sem = asyncio.Semaphore(CONCURRENCY)

    async def bounded(client, tenant):
        async with sem:
            return await discover_tenant(
                client,
                tenant,
                existing_companies,
                early_career_only=not args.all_roles,
            )

    async with httpx.AsyncClient(headers=UA, timeout=TIMEOUT, follow_redirects=True) as client:
        results = await asyncio.gather(*(bounded(client, t) for t in candidates))

    qualified = [r for r in results if r]
    print(f"\nDiscovered {len(qualified)} qualified Workday company/companies:")

    new_companies = []
    for comp, matched_jobs in qualified:
        ident = comp["ats_identifier"]
        name = comp["company_name"]
        is_new = ident not in existing_idents and name.lower() not in existing_names
        status_tag = "[NEW]" if is_new else "[EXISTS]"
        print(f"  {status_tag} {name:<22} -> {ident} ({len(matched_jobs)} early-career matches)")
        for m in matched_jobs[:2]:
            print(f"         - {m['title']} ({m['location']})")
        if is_new:
            new_companies.append(comp)

    print(f"\nTotal new companies to add: {len(new_companies)}")

    if new_companies and not args.dry_run:
        updated = existing_companies + new_companies
        updated.sort(key=lambda c: c["company_name"].lower())
        SEED_FILE.write_text(json.dumps(updated, indent=2) + "\n")
        print(f"Successfully saved {len(new_companies)} new companies to {SEED_FILE} (total: {len(updated)}).")

        try:
            from db import queries
            written = queries.upsert_companies(new_companies)
            print(f"Synchronized {written} new companies to database ({DB_ENV}).")
        except Exception as exc:
            print(f"Database sync note: {exc}")

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
