"""Harvest and validate companies from multiple open job boards and datasets.

Extracts company entries from live listings, maps them to supported ATS
platforms (Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Teamtailor),
validates their feeds, and updates seed/companies.json and seed.json.
"""

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from collections import Counter
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.validate_companies import (
    CHECKS,
    SIGNATURES,
    construct_career_url,
    validate_company,
)

logger = logging.getLogger("harvest_companies")

SEED_FILE = PROJECT_ROOT / "seed" / "companies.json"

SOURCES = [
    "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json",
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2025-Internships/dev/.github/scripts/listings.json",
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/.github/scripts/listings.json",
    "https://raw.githubusercontent.com/SimplifyJobs/Summer2024-Internships/dev/.github/scripts/listings.json",
]

UA = "JobScanr/0.1 (personal job alert; contact: local-user)"


def clean_company_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    return name


def extract_candidate(company_name: str, url: str) -> dict | None:
    if not company_name or not url:
        return None
    name = clean_company_name(company_name)
    for platform, rx in SIGNATURES:
        m = rx.search(url)
        if m:
            if platform == "workday":
                ident = f"{m.group(1)}|{m.group(2)}|{m.group(3)}"
            else:
                ident = m.group(1).lower()
            career_url = construct_career_url(platform, ident)
            if not career_url:
                career_url = url
            return {
                "company_name": name,
                "career_url": career_url,
                "ats_platform": platform,
                "ats_identifier": ident,
            }
    return None


async def fetch_source_listings(client: httpx.AsyncClient, source_url: str) -> list[dict]:
    try:
        r = await client.get(source_url)
        if r.status_code == 200:
            return r.json()
        logger.warning("Failed to fetch %s: HTTP %d", source_url, r.status_code)
    except Exception as exc:
        logger.warning("Error fetching %s: %s", source_url, exc)
    return []


async def harvest(limit: int | None = None, concurrency: int = 25) -> list[dict]:
    existing_companies = []
    if SEED_FILE.exists():
        try:
            existing_companies = json.loads(SEED_FILE.read_text())
        except Exception as exc:
            logger.error("Could not read %s: %s", SEED_FILE, exc)

    seen_keys = {
        (c["ats_platform"], c["ats_identifier"]) for c in existing_companies
    }
    logger.info("Loaded %d existing companies from %s", len(existing_companies), SEED_FILE)

    async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": UA}) as client:
        tasks = [fetch_source_listings(client, src) for src in SOURCES]
        all_results = await asyncio.gather(*tasks)

    candidates = {}
    for listings in all_results:
        for item in listings:
            cand = extract_candidate(item.get("company_name", ""), item.get("url", ""))
            if not cand:
                continue
            key = (cand["ats_platform"], cand["ats_identifier"])
            if key not in seen_keys and key not in candidates:
                candidates[key] = cand

    logger.info("Found %d new candidate companies across sources", len(candidates))

    sem = asyncio.Semaphore(concurrency)
    ashby_sem = asyncio.Semaphore(3)

    async def bounded_validate(client: httpx.AsyncClient, cand: dict):
        gate = ashby_sem if cand["ats_platform"] == "ashby" else sem
        async with gate:
            if cand["ats_platform"] == "ashby":
                await asyncio.sleep(0.2)
            res = await validate_company(client, cand)
            return res

    logger.info("Validating candidates against live ATS APIs...")
    async with httpx.AsyncClient(timeout=20.0, headers={"User-Agent": UA}, follow_redirects=True) as client:
        val_tasks = [bounded_validate(client, cand) for cand in candidates.values()]
        val_results = await asyncio.gather(*val_tasks)

    verified_new = [
        {
            "company_name": r["company_name"],
            "career_url": r["career_url"],
            "ats_platform": r["ats_platform"],
            "ats_identifier": r["ats_identifier"],
        }
        for r in val_results
        if r.get("ok")
    ]

    logger.info("Validated %d / %d candidates successfully", len(verified_new), len(candidates))

    if limit is not None and limit > 0:
        verified_new = verified_new[:limit]

    combined = list(existing_companies) + verified_new
    combined.sort(key=lambda x: x["company_name"].lower())

    SEED_FILE.parent.mkdir(parents=True, exist_ok=True)
    SEED_FILE.write_text(json.dumps(combined, indent=2) + "\n")
    logger.info("Saved %d total companies to %s", len(combined), SEED_FILE)

    by_plat = Counter(c["ats_platform"] for c in combined)
    print("\n" + "=" * 50)
    print(f"Total Companies in Seed: {len(combined)}")
    print("Breakdown by ATS Platform:")
    for plat, count in sorted(by_plat.items(), key=lambda x: -x[1]):
        print(f"  {plat:<18}: {count}")
    print("=" * 50 + "\n")

    return combined


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Harvest and validate companies for JobScanr seed.")
    parser.add_argument("--limit", type=int, default=None, help="Max new companies to add")
    parser.add_argument("--concurrency", type=int, default=25, help="Concurrent validation requests")
    args = parser.parse_args()

    asyncio.run(harvest(limit=args.limit, concurrency=args.concurrency))


if __name__ == "__main__":
    main()
