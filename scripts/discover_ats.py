"""Re-detect the current ATS for companies whose stored feed failed validation.

Fetches each company's career_url (following redirects) and fingerprints the
final URL + page HTML for known ATS signatures. Prints proposed corrections
as JSON so they can be reviewed before applying them to seed/companies.json.

Usage: python -m scripts.discover_ats < companies_failed.json
Input format: array of {company_name, career_url} objects.
"""

import asyncio
import json
import re
import sys

import httpx

CONCURRENCY = 8
TIMEOUT = 20.0
UA = "JobScanr/0.1 (personal job alert; contact: local-user)"

SIGNATURES = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)\.greenhouse\.io/([a-zA-Z0-9_-]+)")),
    ("lever", re.compile(r"jobs\.(?:eu\.)?lever\.co/([a-zA-Z0-9_-]+)")),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([a-zA-Z0-9_.-]+)")),
    ("smartrecruiters", re.compile(r"careers\.smartrecruiters\.com/([a-zA-Z0-9_-]+)")),
    ("workable", re.compile(r"(?:apply|jobs)\.workable\.com/([a-zA-Z0-9_-]+)")),
]

DROP_SIGNATURES = [
    "myworkdayjobs.com", "workday", "teamtailor.com", "rippling",
    "pinpoint", "recruitee", "personio", "bamboohr", "jazzhr",
    "smartrecruiters.com", "eightfold.ai", "phenompeople", "icims",
    "successfactors", "oraclecloud.com", "greenhouse.io/embed",
]


def fingerprint(url: str, html: str) -> tuple[str, str] | None:
    haystack = url + " " + html[:200_000]
    for platform, pattern in SIGNATURES:
        m = pattern.search(haystack)
        if m:
            return platform, m.group(1)
    return None


async def probe(client: httpx.AsyncClient, company: dict) -> dict:
    name, url = company["company_name"], company["career_url"]
    result = {"company_name": name, "career_url": url, "action": "drop", "found": None}
    if not url:
        return result
    try:
        r = await client.get(url)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}"
        return result
    if r.status_code != 200:
        result["action"] = "drop"
        result["reason"] = f"career page HTTP {r.status_code}"
        return result
    final_url = str(r.url)
    lower = (final_url + " " + r.text[:50_000]).lower()
    if any(sig in lower for sig in DROP_SIGNATURES):
        result["action"] = "drop"
        result["reason"] = "unsupported ATS detected"
        return result
    found = fingerprint(final_url, r.text)
    if found:
        platform, ident = found
        old = company.get("ats_identifier")
        if platform == company.get("ats_platform") and ident == old:
            result["action"] = "investigate"
            result["reason"] = f"page live but API 404s for {platform}/{ident}"
            return result
        result["action"] = "fix"
        result["found"] = {"ats_platform": platform, "ats_identifier": ident}
    else:
        result["reason"] = "no known ATS signature found"
    return result


async def main() -> int:
    companies = json.load(sys.stdin)
    print(f"Probing {len(companies)} career pages...\n", file=sys.stderr)

    sem = asyncio.Semaphore(CONCURRENCY)

    async def bounded(client, c):
        async with sem:
            return await probe(client, c)

    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": UA}, follow_redirects=True) as client:
        results = await asyncio.gather(*(bounded(client, c) for c in companies))

    fixed = [r for r in results if r["action"] == "fix"]
    dropped = [r for r in results if r["action"] == "drop"]
    print(f"Fixable: {len(fixed)}, Drop: {len(dropped)}\n", file=sys.stderr)
    for r in sorted(results, key=lambda x: x["action"]):
        line = f"{r['company_name']:<28} {r['action']:<5}"
        if r["found"]:
            line += f" -> {r['found']['ats_platform']}/{r['found']['ats_identifier']}"
        elif r.get("reason"):
            line += f" ({r['reason']})"
        elif r.get("error"):
            line += f" ({r['error']})"
        print(line, file=sys.stderr)

    json.dump(results, sys.stdout, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
