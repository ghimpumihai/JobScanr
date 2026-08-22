"""Attempt to recover failed companies by probing candidate ATS identifiers.

For each failed company, generates candidate slugs (aliases, normalized names,
common suffixes), probes them against the relevant public APIs, and emits only
VERIFIED fixes (API confirmed a live job feed).

Usage: python -m scripts.probe_candidates < to_probe.json > verified.json
"""

import asyncio
import json
import re
import sys

import httpx

CONCURRENCY = 12
TIMEOUT = 15.0
UA = "JobScanr/0.1 (personal job alert; contact: local-user)"

# Known renames/migrations (old identifier -> better candidates)
ALIASES = {
    "sentry": ["getsentry"],
    "unity technologies": ["unity3d"],
    "weights & biases": ["wandb"],
    "dbt labs": ["dbtlabsinc"],
    "cursor": ["anysphere", "getcursor"],
    "turso": ["chiselstrike", "tursodatabase"],
    "fly.io": ["flydotio", "flyio"],
    "starrocks": ["starrocksai"],
    "deepl": ["deeplcom", "deep-l"],
    "hugging face": ["huggingface", "hugging-face"],
    "kraken": ["krakenfx", "payward"],
    "klarna": ["klarnase", "klarna-bank"],
    "1password": ["onepassword", "1passwordcareers"],
    "hotjar": ["contentsquare", "hotjar-com"],
    "invision": ["invisionapp"],
    "digitalocean": ["digitalocean-careers"],
}

ASHBY_QUERY = """query ApiJobBoardWithTeams($organizationHostedJobsPageName: String!) {
  jobBoard: jobBoardWithTeams(organizationHostedJobsPageName: $organizationHostedJobsPageName) {
    jobPostings { id title }
  }
}"""


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]", "", name.lower())
    return s


def candidates_for(company: dict) -> dict[str, list[str]]:
    """platform -> ordered list of candidate identifiers."""
    name = company["company_name"]
    ident = company["ats_identifier"]
    base = [ident] + ALIASES.get(name.lower(), [])
    slug = slugify(name)
    variants = list(dict.fromkeys(
        [ident, *base, slug, slug + "hq", ident + "hq", ident.replace("-", ""), ident + "inc"]
    ))
    return {company["ats_platform"]: variants[:8]}


async def ok_greenhouse(client: httpx.AsyncClient, ident: str) -> bool:
    r = await client.get(f"https://boards-api.greenhouse.io/v1/boards/{ident}/jobs")
    return r.status_code == 200 and isinstance(r.json().get("jobs"), list)


async def ok_lever(client: httpx.AsyncClient, ident: str) -> bool:
    r = await client.get(f"https://api.lever.co/v0/postings/{ident}?mode=json")
    return r.status_code == 200 and isinstance(r.json(), list)


async def ok_smartrecruiters(client: httpx.AsyncClient, ident: str) -> bool:
    r = await client.get(f"https://api.smartrecruiters.com/v1/companies/{ident}/postings?limit=1")
    return r.status_code == 200 and isinstance(r.json().get("content"), list)


async def ok_ashby(client: httpx.AsyncClient, ident: str) -> bool:
    r = await client.post(
        "https://jobs.ashbyhq.com/api/non-user-graphql",
        json={"operationName": "ApiJobBoardWithTeams",
              "variables": {"organizationHostedJobsPageName": ident},
              "query": ASHBY_QUERY},
    )
    if r.status_code != 200:
        return False
    board = (r.json().get("data") or {}).get("jobBoard")
    return board is not None


CHECKS = {"greenhouse": ok_greenhouse, "lever": ok_lever,
          "smartrecruiters": ok_smartrecruiters, "ashby": ok_ashby}


async def recover(client: httpx.AsyncClient, company: dict) -> dict | None:
    for platform, candidates in candidates_for(company).items():
        check = CHECKS[platform]
        for ident in candidates:
            try:
                if await check(client, ident):
                    return {"company_name": company["company_name"], "career_url": company["career_url"],
                            "ats_platform": platform, "ats_identifier": ident}
            except Exception:
                continue
    return None


async def main() -> int:
    companies = json.load(sys.stdin)
    print(f"Probing candidates for {len(companies)} companies...\n", file=sys.stderr)
    sem = asyncio.Semaphore(CONCURRENCY)

    async def bounded(client, c):
        async with sem:
            return await recover(client, c)

    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": UA}) as client:
        results = await asyncio.gather(*(bounded(client, c) for c in companies))

    recovered = [r for r in results if r]
    print(f"\nRecovered {len(recovered)}/{len(companies)}:", file=sys.stderr)
    for r in sorted(recovered, key=lambda x: x["company_name"]):
        print(f"  {r['company_name']:<28} -> {r['ats_platform']}/{r['ats_identifier']}", file=sys.stderr)
    print("\nUnrecoverable:", file=sys.stderr)
    for c, r in zip(companies, results):
        if not r:
            print(f"  {c['company_name']}", file=sys.stderr)

    json.dump(recovered, sys.stdout, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
