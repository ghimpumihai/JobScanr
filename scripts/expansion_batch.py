"""One-shot expansion batch: probe curated candidates against live ATS APIs.

Reads /tmp/opencode/candidates.json entries [name, primary_identifier, platform],
tries identifier variants across platforms, emits VERIFIED feeds only.

Usage: python -m scripts.expansion_batch > expansion_verified.json
"""

import asyncio
import json
import re
import sys

import httpx

sys.path.insert(0, ".")
from scripts.probe_candidates import CHECKS  # noqa: E402

CONCURRENCY = 12
TIMEOUT = 15.0
UA = "JobScanr/0.1 (personal job alert; contact: local-user)"

CANDIDATES_FILE = "/tmp/opencode/candidates.json"


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def combos_for(name: str, ident: str, platform: str) -> list[tuple[str, str]]:
    """(platform, identifier) pairs to try, most likely first."""
    slug = slugify(name)
    ids = list(dict.fromkeys([ident, slug, ident.replace("-", ""), slug + "hq"]))
    platforms = [platform, "greenhouse", "ashby", "lever"]
    out, seen = [], set()
    for plat in platforms:
        for i in ids[:3]:
            key = (plat, i)
            if key not in seen:
                seen.add(key)
                out.append(key)
    return out[:6]


async def recover(client: httpx.AsyncClient, name: str, pairs) -> dict | None:
    for platform, ident in pairs:
        check = CHECKS[platform]
        try:
            if await check(client, ident):
                return {"company_name": name,
                        "ats_platform": platform,
                        "ats_identifier": ident}
        except Exception:
            continue
    return None


async def main() -> int:
    raw = json.load(open(CANDIDATES_FILE))
    sem = asyncio.Semaphore(CONCURRENCY)

    async def bounded(client, item):
        name, ident, platform = item
        async with sem:
            return name, await recover(client, name, combos_for(name, ident, platform))

    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": UA}) as client:
        results = await asyncio.gather(*(bounded(client, item) for item in raw))

    recovered = [{"company_name": n, **r} for n, r in results if r]
    print(f"Recovered {len(recovered)}/{len(raw)}:", file=sys.stderr)
    for r in sorted(recovered, key=lambda x: x["company_name"]):
        print(f"  {r['company_name']:<24} -> {r['ats_platform']}/{r['ats_identifier']}",
              file=sys.stderr)

    json.dump(recovered, sys.stdout, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
