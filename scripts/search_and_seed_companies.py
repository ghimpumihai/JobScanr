"""Search, discover, validate, and seed companies hosted on supported ATS platforms.

Supports:
- Bulk sourcing & validation from curated ATS candidate pools (Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Teamtailor).
- Keyword/name search across all supported ATS platforms.
- Active feed validation matching JobScanr's production scrapers.
- Automatic company name resolution, canonical career URL formatting, deduplication, and alphabetical sorting.

Usage:
  # Reach 1500+ total active companies:
  python -m scripts.search_and_seed_companies --target 1500

  # Search for a specific company across all handled ATS platforms:
  python -m scripts.search_and_seed_companies --search "anthropic"
  python -m scripts.search_and_seed_companies --search "linear"

  # Add companies from a specific platform:
  python -m scripts.search_and_seed_companies --platform greenhouse --limit 200
"""

import argparse
import asyncio
import json
import logging
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.validate_companies import (
    ASHBY_QUERY,
    CHECKS,
    SEED_FILE,
    check_ashby,
    check_greenhouse,
    check_lever,
    check_smartrecruiters,
    check_teamtailor,
    check_workday,
    construct_career_url,
)

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).parent.parent
DEFAULT_CONCURRENCY = 30
TIMEOUT = 12.0
UA = "JobScanr/0.1 (personal job alert; contact: local-user)"

BULK_SOURCES = {
    "greenhouse": "https://raw.githubusercontent.com/Feashliaa/job-board-aggregator/main/data/greenhouse_companies.json",
    "lever": "https://raw.githubusercontent.com/Feashliaa/job-board-aggregator/main/data/lever_companies.json",
    "ashby": "https://raw.githubusercontent.com/Feashliaa/job-board-aggregator/main/data/ashby_companies.json",
    "workday": "https://raw.githubusercontent.com/Feashliaa/job-board-aggregator/main/data/workday_companies.json",
}


def clean_company_name(name: str) -> str:
    """Clean company names from page titles or HTML entities."""
    if not name:
        return ""
    # Strip HTML tags
    name = re.sub(r"<[^>]+>", "", name)
    # Remove common title suffixes
    name = re.sub(r"\s*[|–—-]\s*(Careers|Jobs|Job Board|Workday|Openings).*$", "", name, flags=re.I)
    name = re.sub(r"\s+(Careers|Jobs|Job Openings)$", "", name, flags=re.I)
    name = re.sub(r"^Jobs at\s+", "", name, flags=re.I)
    name = re.sub(r"^Careers at\s+", "", name, flags=re.I)
    return name.strip()


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


async def resolve_greenhouse_name(client: httpx.AsyncClient, ident: str) -> str | None:
    try:
        r = await client.get(f"https://boards-api.greenhouse.io/v1/boards/{ident}")
        if r.status_code == 200:
            name = r.json().get("name")
            if name:
                return clean_company_name(name)
    except Exception:
        pass
    return None


async def resolve_lever_name(client: httpx.AsyncClient, ident: str) -> str | None:
    try:
        r = await client.get(f"https://jobs.lever.co/{ident}")
        if r.status_code == 200:
            m = re.search(r"<title>(.*?)</title>", r.text, re.I)
            if m:
                return clean_company_name(m.group(1))
    except Exception:
        pass
    return ident.replace("-", " ").title()


async def resolve_ashby_name(client: httpx.AsyncClient, ident: str) -> str | None:
    try:
        r = await client.get(f"https://jobs.ashbyhq.com/{ident}")
        if r.status_code == 200:
            m = re.search(r"<title>(.*?)</title>", r.text, re.I)
            if m:
                return clean_company_name(m.group(1))
    except Exception:
        pass
    return ident.replace("-", " ").replace(".", " ").title()


def resolve_workday_name(ident: str) -> str:
    parts = ident.split("|")
    tenant = parts[0]
    return tenant.replace("-", " ").replace("_", " ").title()


async def search_company_across_ats(client: httpx.AsyncClient, query: str) -> list[dict]:
    """Search for a company keyword across all handled ATS platforms."""
    slug = slugify(query)
    variants = list(dict.fromkeys([
        slug,
        slug + "hq",
        slug + "careers",
        slug + "tech",
        f"get{slug}",
        query.lower().replace(" ", "-"),
        query.lower().replace(" ", ""),
    ]))

    found = []

    # 1. Probe Greenhouse
    for v in variants:
        try:
            ok, detail = await check_greenhouse(client, v)
            if ok:
                name = await resolve_greenhouse_name(client, v) or query.title()
                found.append({
                    "company_name": name,
                    "career_url": construct_career_url("greenhouse", v),
                    "ats_platform": "greenhouse",
                    "ats_identifier": v,
                    "_detail": detail,
                })
                break
        except Exception:
            pass

    # 2. Probe Lever
    for v in variants:
        try:
            ok, detail = await check_lever(client, v)
            if ok:
                name = await resolve_lever_name(client, v) or query.title()
                found.append({
                    "company_name": name,
                    "career_url": construct_career_url("lever", v),
                    "ats_platform": "lever",
                    "ats_identifier": v,
                    "_detail": detail,
                })
                break
        except Exception:
            pass

    # 3. Probe Ashby
    for v in variants:
        try:
            ok, detail = await check_ashby(client, v)
            if ok:
                name = await resolve_ashby_name(client, v) or query.title()
                found.append({
                    "company_name": name,
                    "career_url": construct_career_url("ashby", v),
                    "ats_platform": "ashby",
                    "ats_identifier": v,
                    "_detail": detail,
                })
                break
        except Exception:
            pass

    # 4. Probe SmartRecruiters
    for v in variants:
        try:
            ok, detail = await check_smartrecruiters(client, v)
            if ok:
                found.append({
                    "company_name": query.title(),
                    "career_url": construct_career_url("smartrecruiters", v),
                    "ats_platform": "smartrecruiters",
                    "ats_identifier": v,
                    "_detail": detail,
                })
                break
        except Exception:
            pass

    # 5. Probe Teamtailor
    for v in variants:
        try:
            ok, detail = await check_teamtailor(client, v)
            if ok:
                found.append({
                    "company_name": query.title(),
                    "career_url": construct_career_url("teamtailor", v),
                    "ats_platform": "teamtailor",
                    "ats_identifier": v,
                    "_detail": detail,
                })
                break
        except Exception:
            pass

    return found


async def validate_candidate(
    client: httpx.AsyncClient,
    platform: str,
    identifier: str,
    min_jobs: int = 1,
) -> dict | None:
    """Validate a candidate ATS identifier and resolve its metadata."""
    check_func = CHECKS.get(platform)
    if not check_func:
        return None

    try:
        ok, detail = await check_func(client, identifier)
        if not ok:
            return None

        # Extract job count from detail if available e.g. "12 jobs"
        count_match = re.search(r"(\d+)", detail)
        job_count = int(count_match.group(1)) if count_match else 1
        if job_count < min_jobs:
            return None

        # Resolve display name
        if platform == "greenhouse":
            name = await resolve_greenhouse_name(client, identifier)
            if not name:
                name = identifier.replace("-", " ").title()
        elif platform == "lever":
            name = await resolve_lever_name(client, identifier)
            if not name:
                name = identifier.replace("-", " ").title()
        elif platform == "ashby":
            name = await resolve_ashby_name(client, identifier)
            if not name:
                name = identifier.replace("-", " ").title()
        elif platform == "workday":
            name = resolve_workday_name(identifier)
        else:
            name = identifier.replace("-", " ").title()

        career_url = construct_career_url(platform, identifier)
        if not career_url:
            return None

        return {
            "company_name": name,
            "career_url": career_url,
            "ats_platform": platform,
            "ats_identifier": identifier,
        }
    except Exception:
        return None


def load_seed(seed_path: Path) -> list[dict]:
    if not seed_path.exists():
        return []
    return json.loads(seed_path.read_text(encoding="utf-8"))


def save_seed(seed_path: Path, companies: list[dict]) -> None:
    # Deduplicate by (ats_platform, ats_identifier)
    seen_keys = set()
    seen_names = set()
    deduped = []

    # Sort companies alphabetically by company_name
    for c in sorted(companies, key=lambda x: x.get("company_name", "").lower()):
        key = (c.get("ats_platform"), c.get("ats_identifier"))
        name_key = c.get("company_name", "").strip().lower()
        if not key[0] or not key[1] or not name_key:
            continue
        if key in seen_keys:
            continue
        # Avoid exact duplicate company name with same platform
        if (name_key, key[0]) in seen_names:
            continue
        seen_keys.add(key)
        seen_names.add((name_key, key[0]))

        deduped.append({
            "company_name": c["company_name"].strip(),
            "career_url": c["career_url"].strip(),
            "ats_platform": c["ats_platform"].strip(),
            "ats_identifier": c["ats_identifier"].strip(),
        })

    # Write formatted JSON to seed_path
    content = json.dumps(deduped, indent=2, ensure_ascii=False) + "\n"
    seed_path.write_text(content, encoding="utf-8")


async def main_async() -> int:
    parser = argparse.ArgumentParser(
        description="Search, validate, and seed companies for JobScanr."
    )
    parser.add_argument(
        "--target",
        type=int,
        default=0,
        help="Target total number of companies in seed file (e.g. 1500).",
    )
    parser.add_argument(
        "--search",
        type=str,
        default="",
        help="Search for a company keyword across all ATS platforms.",
    )
    parser.add_argument(
        "--platform",
        type=str,
        default="",
        choices=["", "greenhouse", "lever", "ashby", "workday", "smartrecruiters", "teamtailor"],
        help="Limit sourcing or probing to specific ATS platform.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of new companies to add.",
    )
    parser.add_argument(
        "--min-jobs",
        type=int,
        default=1,
        help="Minimum active job postings required (default 1).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=f"Concurrency level (default {DEFAULT_CONCURRENCY}).",
    )
    parser.add_argument(
        "--seed-file",
        type=Path,
        default=SEED_FILE,
        help="Path to companies seed file (default seed/companies.json).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate candidates without modifying seed files.",
    )

    args = parser.parse_args()

    current_seed = load_seed(args.seed_file)
    print(f"Loaded {len(current_seed)} companies from {args.seed_file}")

    existing_keys = {
        (c["ats_platform"], c["ats_identifier"]) for c in current_seed
    }
    existing_names = {c["company_name"].lower() for c in current_seed}

    sem = asyncio.Semaphore(args.concurrency)
    ashby_sem = asyncio.Semaphore(4)

    async with httpx.AsyncClient(
        timeout=TIMEOUT,
        headers={"User-Agent": UA},
        follow_redirects=True,
    ) as client:
        # Mode 1: Search specific company
        if args.search:
            print(f"Searching across supported ATS platforms for '{args.search}'...")
            found = await search_company_across_ats(client, args.search)
            if not found:
                print(f"No active ATS feeds found for '{args.search}'.")
                return 1

            new_added = 0
            for item in found:
                detail = item.pop("_detail", "")
                key = (item["ats_platform"], item["ats_identifier"])
                status = "EXISTING" if key in existing_keys else "NEW"
                print(f"[{status}] {item['company_name']} ({item['ats_platform']}): {item['career_url']} ({detail})")
                if not args.dry_run and key not in existing_keys:
                    current_seed.append(item)
                    existing_keys.add(key)
                    new_added += 1

            if not args.dry_run and new_added > 0:
                save_seed(args.seed_file, current_seed)
                print(f"Added {new_added} company entries. Total: {len(current_seed)}")
            return 0

        # Mode 2: Bulk expansion to reach target or limit
        target_count = args.target if args.target > 0 else (len(current_seed) + args.limit if args.limit > 0 else 1000)
        needed = target_count - len(current_seed)

        if needed <= 0 and not args.limit:
            print(f"Current seed already has {len(current_seed)} companies (target: {target_count}). Nothing to add.")
            return 0

        needed = max(needed, args.limit or 0)
        print(f"Target count: {target_count} (need ~{needed} more valid companies). Sourcing candidates...")

        platforms = [args.platform] if args.platform else ["greenhouse", "lever", "workday", "ashby"]

        candidate_pools: dict[str, list[str]] = {}
        for plat in platforms:
            url = BULK_SOURCES.get(plat)
            if not url:
                continue
            try:
                print(f"Fetching candidate pool for {plat}...")
                r = await client.get(url)
                if r.status_code == 200:
                    raw_list = r.json()
                    fresh = [
                        item for item in raw_list
                        if (plat, item) not in existing_keys
                    ]
                    candidate_pools[plat] = fresh
                    print(f"  {plat}: {len(fresh)} new candidates available")
            except Exception as exc:
                print(f"  {plat}: failed to fetch candidate pool ({exc})")

        total_candidates = sum(len(v) for v in candidate_pools.values())
        print(f"Total fresh candidates across platforms: {total_candidates}")

        newly_validated: list[dict] = []

        async def check_bounded(plat: str, ident: str):
            if len(newly_validated) >= needed:
                return None
            gate = ashby_sem if plat == "ashby" else sem
            async with gate:
                if plat == "ashby":
                    await asyncio.sleep(0.2)
                res = await validate_candidate(client, plat, ident, min_jobs=args.min_jobs)
                if res and len(newly_validated) < needed:
                    key = (res["ats_platform"], res["ats_identifier"])
                    name_lower = res["company_name"].lower()
                    if key not in existing_keys and name_lower not in existing_names:
                        existing_keys.add(key)
                        existing_names.add(name_lower)
                        newly_validated.append(res)
                        print(f"  [+{len(newly_validated)}/{needed}] {res['company_name']} ({res['ats_platform']}/{res['ats_identifier']})")
                return res

        tasks = []
        max_per_plat = max(needed * 2, 400)
        for plat, cands in candidate_pools.items():
            for ident in cands[:max_per_plat]:
                tasks.append((plat, ident))

        print(f"Validating candidate feeds with concurrency {args.concurrency}...")

        chunk_size = 120
        for i in range(0, len(tasks), chunk_size):
            if len(newly_validated) >= needed:
                break
            chunk = tasks[i : i + chunk_size]
            await asyncio.gather(*(check_bounded(plat, ident) for plat, ident in chunk))

        print(f"\nSuccessfully validated {len(newly_validated)} new companies with active feeds!")

        if args.dry_run:
            print("Dry run enabled — seed files not modified.")
            return 0

        current_seed.extend(newly_validated)
        save_seed(args.seed_file, current_seed)
        final_count = len(load_seed(args.seed_file))
        print(f"Updated {args.seed_file} successfully.")
        print(f"New total company count: {final_count}")
        return 0


def main():
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
