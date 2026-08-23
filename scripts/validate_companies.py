"""Phase 0: validate that every company in seed/companies.json has a live ATS feed.

Usage: python -m scripts.validate_companies
Exits 1 if more than 5% of companies fail.
"""

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

import httpx

SEED_FILE = Path(__file__).parent.parent / "seed" / "companies.json"
CONCURRENCY = 10
TIMEOUT = 20.0
FAIL_THRESHOLD = 0.05

UA = "JobScanr/0.1 (personal job alert; contact: local-user)"

ASHBY_QUERY = """query ApiJobBoardWithTeams($organizationHostedJobsPageName: String!) {
  jobBoard: jobBoardWithTeams(organizationHostedJobsPageName: $organizationHostedJobsPageName) {
    teams { id name }
    jobPostings { id title locationName workplaceType employmentType }
  }
}"""


async def check_greenhouse(client: httpx.AsyncClient, ident: str) -> tuple[bool, str]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{ident}/jobs"
    r = await client.get(url)
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}"
    jobs = r.json().get("jobs")
    if not isinstance(jobs, list):
        return False, "no 'jobs' array in response"
    return True, f"{len(jobs)} jobs"


async def check_lever(client: httpx.AsyncClient, ident: str) -> tuple[bool, str]:
    url = f"https://api.lever.co/v0/postings/{ident}?mode=json"
    r = await client.get(url)
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}"
    data = r.json()
    if not isinstance(data, list):
        return False, "response is not a JSON list"
    return True, f"{len(data)} jobs"


async def check_smartrecruiters(client: httpx.AsyncClient, ident: str) -> tuple[bool, str]:
    url = f"https://api.smartrecruiters.com/v1/companies/{ident}/postings?limit=1"
    r = await client.get(url)
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}"
    content = r.json().get("content")
    if not isinstance(content, list):
        return False, "no 'content' array in response"
    total = r.json().get("totalFound", "?")
    return True, f"{total} jobs"


async def check_ashby(client: httpx.AsyncClient, ident: str) -> tuple[bool, str]:
    # Ashby soft-throttles bursts with HTTP 200 + null data, so retry.
    for attempt in range(3):
        r = await client.post(
            "https://jobs.ashbyhq.com/api/non-user-graphql",
            json={
                "operationName": "ApiJobBoardWithTeams",
                "variables": {"organizationHostedJobsPageName": ident},
                "query": ASHBY_QUERY,
            },
        )
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"
        body = r.json()
        board = (body.get("data") or {}).get("jobBoard")
        if board is not None:
            return True, f"{len(board['jobPostings'])} jobs"
        await asyncio.sleep(1.0 + attempt)
    return False, "throttled after retries"


CHECKS = {
    "greenhouse": check_greenhouse,
    "lever": check_lever,
    "smartrecruiters": check_smartrecruiters,
    "ashby": check_ashby,
}


async def validate_company(client: httpx.AsyncClient, company: dict) -> dict:
    platform = company["ats_platform"]
    check = CHECKS[platform]
    try:
        ok, detail = await check(client, company["ats_identifier"])
    except Exception as exc:
        ok, detail = False, f"{type(exc).__name__}: {exc}"
    return {**company, "ok": ok, "detail": detail}


async def main() -> int:
    companies = json.loads(SEED_FILE.read_text())
    print(f"Validating {len(companies)} companies...\n")

    sem = asyncio.Semaphore(CONCURRENCY)
    ashby_sem = asyncio.Semaphore(4)  # Ashby throttles harder than the rest

    async def bounded(client, c):
        gate = ashby_sem if c["ats_platform"] == "ashby" else sem
        async with gate:
            return await validate_company(client, c)

    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": UA}, follow_redirects=True) as client:
        results = await asyncio.gather(*(bounded(client, c) for c in companies))

    failures = [r for r in results if not r["ok"]]
    by_platform_ok = Counter(r["ats_platform"] for r in results if r["ok"])
    by_platform_all = Counter(r["ats_platform"] for r in results)

    print(f"{'COMPANY':<28} {'PLATFORM':<16} RESULT")
    for r in sorted(results, key=lambda x: (x["ok"] is False, x["ats_platform"], x["company_name"])):
        mark = "PASS" if r["ok"] else "FAIL"
        name = r["company_name"][:27]
        suffix = "" if r["ok"] else f"  ({r['detail']})"
        count = f"{r['detail']}" if r["ok"] else ""
        print(f"{name:<28} {r['ats_platform']:<16} {mark:<5} {count}{suffix}")

    print("\nSummary by platform:")
    for platform, total in sorted(by_platform_all.items()):
        print(f"  {platform:<16} {by_platform_ok[platform]}/{total} pass")

    fail_rate = len(failures) / len(results)
    print(f"\n{len(failures)} failures out of {len(results)} ({fail_rate:.1%})")
    verdict = "OK" if fail_rate <= FAIL_THRESHOLD else "TOO MANY FAILURES — fix companies.json"
    print(f"Verdict: {verdict}")
    return 0 if fail_rate <= FAIL_THRESHOLD else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
