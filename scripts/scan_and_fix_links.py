"""Scan production scrape logs/failures, discover & verify working ATS links, and update seed/companies.json.

Usage:
  python -m scripts.scan_and_fix_links --log-file scrape.log --report-file fix_report.md
  python -m scripts.scan_and_fix_links --failures-file failures.json
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

from scripts.validate_companies import (
    check_ashby,
    check_google,
    check_greenhouse,
    check_lever,
    check_workday,
)

SEED_FILE = Path(__file__).parent.parent / "seed" / "companies.json"
DEFAULT_REPORT_FILE = Path(__file__).parent.parent / "fix_report.md"
CONCURRENCY = 8
TIMEOUT = 15.0
UA = "JobScanr/0.1 (personal job alert; automated link fixer)"

FAIL_LINE_RE = re.compile(
    r"^\s*(?:FAIL\s+)?(?P<name>[^()]+?)\s+\((?P<platform>[a-zA-Z0-9_-]+)\):\s*(?P<error>.*)$"
)

SIGNATURES = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)\.greenhouse\.io/([a-zA-Z0-9_-]+)")),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([a-zA-Z0-9_.-]+)")),
    ("lever", re.compile(r"jobs\.(?:eu\.)?lever\.co/([a-zA-Z0-9_-]+)")),
    (
        "workday",
        re.compile(
            r"https://([a-zA-Z0-9_-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([a-zA-Z0-9_-]+)"
        ),
    ),
]

ALIASES: dict[str, list[str]] = {
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

CHECKS = {
    "greenhouse": check_greenhouse,
    "ashby": check_ashby,
    "lever": check_lever,
    "workday": check_workday,
    "google": check_google,
}


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def parse_failures_from_log(log_text: str) -> list[dict]:
    failures = []
    seen = set()
    for line in log_text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = FAIL_LINE_RE.match(line)
        if m:
            name = m.group("name").strip()
            platform = m.group("platform").strip()
            error = m.group("error").strip()
            key = (name.lower(), platform.lower())
            if key not in seen:
                seen.add(key)
                failures.append({
                    "company_name": name,
                    "ats_platform": platform,
                    "error": error,
                    "is_404": "404" in error or "Not Found" in error,
                })
        elif "404" in line or "Client error" in line:
            # Fallback scan for lines containing 404
            pass
    return failures


async def verify_ats(client: httpx.AsyncClient, platform: str, ident: str) -> tuple[bool, str]:
    check = CHECKS.get(platform)
    if not check:
        return False, f"unsupported platform {platform}"
    try:
        return await check(client, ident)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def fingerprint_url_and_html(url: str, html_text: str) -> tuple[str, str] | None:
    haystack = url + " " + (html_text[:200_000] if html_text else "")
    for platform, pattern in SIGNATURES:
        m = pattern.search(haystack)
        if m:
            if platform == "workday":
                tenant, wd, site = m.group(1), m.group(2), m.group(3)
                return platform, f"{tenant}|{wd}|{site}"
            return platform, m.group(1)
    return None


async def probe_career_url(client: httpx.AsyncClient, url: str) -> tuple[str, str, str] | None:
    """Follow redirects and search for ATS signature in URL and HTML.
    Returns (platform, identifier, final_url) if found.
    """
    if not url:
        return None
    try:
        r = await client.get(url, follow_redirects=True)
        final_url = str(r.url)
        found = fingerprint_url_and_html(final_url, r.text)
        if found:
            return found[0], found[1], final_url
    except Exception:
        pass

    # Try common subpaths if original URL failed
    try:
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        for path in ["/careers", "/jobs"]:
            alt_url = base + path
            if alt_url == url:
                continue
            try:
                r = await client.get(alt_url, follow_redirects=True)
                if r.status_code == 200:
                    found = fingerprint_url_and_html(str(r.url), r.text)
                    if found:
                        return found[0], found[1], str(r.url)
            except Exception:
                continue
    except Exception:
        pass

    return None


async def probe_workday_clusters(client: httpx.AsyncClient, tenant: str) -> str | None:
    """Check wd1..wd6 for Workday career site."""
    for wd in [5, 3, 4, 2, 6, 1]:
        host = f"https://{tenant}.wd{wd}.myworkdayjobs.com"
        try:
            r = await client.get(f"{host}/robots.txt")
            if r.status_code != 200:
                continue
            m = re.search(r"Sitemap:\s*\S+?/([^/]+)/siteMap\.xml", r.text or "")
            if m:
                site = m.group(1)
                ident = f"{tenant}|wd{wd}|{site}"
                ok, _ = await check_workday(client, ident)
                if ok:
                    return ident
        except Exception:
            continue
    return None


def generate_candidate_identifiers(company: dict) -> list[str]:
    name = company.get("company_name") or company.get("name") or ""
    current_ident = company.get("ats_identifier") or ""
    slug = slugify(name)
    variants = [slug]
    if current_ident and current_ident != slug:
        variants.append(current_ident)
    for alias in ALIASES.get(name.lower(), []):
        variants.append(alias)
    variants.extend([
        f"{slug}hq",
        f"{slug}careers",
        f"{slug}-careers",
        f"{slug}jobs",
        f"{slug}inc",
        f"{slug}tech",
    ])
    if "-" in current_ident:
        variants.append(current_ident.replace("-", ""))
    return list(dict.fromkeys(v for v in variants if v))


def construct_career_url(platform: str, identifier: str) -> str:
    """Construct canonical career board URL for a given ATS platform and identifier."""
    if not platform or not identifier:
        return ""
    if platform == "ashby":
        return f"https://jobs.ashbyhq.com/{identifier}"
    if platform == "greenhouse":
        return f"https://job-boards.greenhouse.io/{identifier}"
    if platform == "lever":
        return f"https://jobs.lever.co/{identifier}"
    if platform == "workday" and "|" in identifier:
        parts = identifier.split("|")
        if len(parts) == 3:
            tenant, wd, site = parts
            return f"https://{tenant}.{wd}.myworkdayjobs.com/{site}"
    if platform == "smartrecruiters":
        return f"https://careers.smartrecruiters.com/{identifier}"
    return ""


async def recover_company(client: httpx.AsyncClient, company: dict) -> dict:
    """Attempt recovery for a failed company. Returns resolution dict."""
    name = company.get("company_name") or company.get("name") or ""
    old_platform = company.get("ats_platform")
    old_ident = company.get("ats_identifier")
    career_url = company.get("career_url") or ""

    res = {
        "company_name": name,
        "old_platform": old_platform,
        "old_ident": old_ident,
        "status": "unresolved",
        "new_platform": None,
        "new_ident": None,
        "new_career_url": None,
        "verification_detail": None,
        "reason": None,
    }

    # Step 1: Check if old endpoint is actually still valid (transient glitch)
    if old_platform and old_ident:
        ok, detail = await verify_ats(client, old_platform, old_ident)
        if ok:
            res["status"] = "transient"
            res["reason"] = f"old endpoint now responding ({detail})"
            return res

    # Step 2: Try career_url redirects & page fingerprinting
    if career_url:
        hit = await probe_career_url(client, career_url)
        if hit:
            plat, ident, final_url = hit
            ok, detail = await verify_ats(client, plat, ident)
            if ok:
                res["status"] = "recovered"
                res["new_platform"] = plat
                res["new_ident"] = ident
                res["new_career_url"] = final_url
                res["verification_detail"] = detail
                res["reason"] = f"fingerprinted from career URL ({plat}/{ident})"
                return res

    # Step 3: Probe candidate slug variants across supported platforms
    candidates = generate_candidate_identifiers(company)
    # Priority order: try old platform first, then ashby, greenhouse, lever
    platform_order = [p for p in [old_platform, "ashby", "greenhouse", "lever"] if p in CHECKS]
    seen_platforms = set()
    ordered_platforms = []
    for p in platform_order:
        if p not in seen_platforms:
            ordered_platforms.append(p)
            seen_platforms.add(p)

    for plat in ordered_platforms:
        for ident in candidates:
            if plat == old_platform and ident == old_ident:
                continue
            ok, detail = await verify_ats(client, plat, ident)
            if ok:
                res["status"] = "recovered"
                res["new_platform"] = plat
                res["new_ident"] = ident
                res["new_career_url"] = construct_career_url(plat, ident)
                res["verification_detail"] = detail
                res["reason"] = f"verified candidate {plat}/{ident}"
                return res

    # Step 4: If Workday, probe clusters
    if old_platform == "workday" or "myworkdayjobs.com" in career_url:
        tenant = (old_ident.split("|")[0] if old_ident and "|" in old_ident else slugify(name))
        wd_ident = await probe_workday_clusters(client, tenant)
        if wd_ident:
            ok, detail = await verify_ats(client, "workday", wd_ident)
            if ok:
                res["status"] = "recovered"
                res["new_platform"] = "workday"
                res["new_ident"] = wd_ident
                res["new_career_url"] = construct_career_url("workday", wd_ident)
                res["verification_detail"] = detail
                res["reason"] = f"verified workday cluster ({wd_ident})"
                return res

    res["status"] = "unrecoverable"
    res["reason"] = "no live ATS coordinates could be verified"
    return res


def apply_fixes_to_companies(companies: list[dict],
                             recoveries: list[dict]) -> tuple[list[dict], int]:
    """Updates companies list in-place with verified recoveries. Returns (updated_list, count)."""
    by_name = {c["company_name"].lower(): c for c in companies}
    by_ident = {(c["ats_platform"], c["ats_identifier"]): c for c in companies}

    fixed_count = 0
    for r in recoveries:
        if r["status"] != "recovered":
            continue
        comp = by_ident.get((r["old_platform"], r["old_ident"])) or by_name.get(r["company_name"].lower())
        if comp:
            comp["ats_platform"] = r["new_platform"]
            comp["ats_identifier"] = r["new_ident"]
            new_url = r.get("new_career_url") or construct_career_url(r["new_platform"], r["new_ident"])
            if new_url:
                comp["career_url"] = new_url
            fixed_count += 1
    return companies, fixed_count


def generate_report_markdown(recoveries: list[dict], failures_count: int) -> str:
    recovered = [r for r in recoveries if r["status"] == "recovered"]
    transient = [r for r in recoveries if r["status"] == "transient"]
    unrecoverable = [r for r in recoveries if r["status"] == "unrecoverable"]

    lines = [
        "# Automated ATS Link Repair Report",
        "",
        "## Summary",
        f"- **Scanned Failures / Errors**: {failures_count}",
        f"- **Successfully Verified & Fixed**: {len(recovered)}",
        f"- **Transient (Self-Resolved)**: {len(transient)}",
        f"- **Unrecoverable (Requires Manual Review)**: {len(unrecoverable)}",
        "",
    ]

    if recovered:
        lines.append("## Verified Fixes (Applied to `seed/companies.json`)")
        lines.append("| Company | Old ATS | New ATS | Verified Jobs | Note |")
        lines.append("|---|---|---|---|---|")
        for r in recovered:
            old_str = f"{r['old_platform']}/{r['old_ident']}"
            new_str = f"{r['new_platform']}/{r['new_ident']}"
            detail = r.get("verification_detail") or "OK"
            reason = r.get("reason") or ""
            lines.append(f"| {r['company_name']} | `{old_str}` | `{new_str}` | {detail} | {reason} |")
        lines.append("")

    if unrecoverable:
        lines.append("## Unrecoverable Failures (Manual Review Needed)")
        lines.append("| Company | Current ATS | Issue |")
        lines.append("|---|---|---|")
        for r in unrecoverable:
            cur_str = f"{r['old_platform']}/{r['old_ident']}"
            reason = r.get("reason") or "unresolved"
            lines.append(f"| {r['company_name']} | `{cur_str}` | {reason} |")
        lines.append("")

    return "\n".join(lines)


async def main_async(args) -> int:
    # 1. Load companies.json
    companies_path = Path(args.companies_file)
    if not companies_path.exists():
        print(f"Error: companies file not found at {companies_path}", file=sys.stderr)
        return 1
    companies = json.loads(companies_path.read_text())
    comp_by_name = {c["company_name"].lower(): c for c in companies}
    comp_by_ident = {(c["ats_platform"], c["ats_identifier"]): c for c in companies}

    # 2. Collect failures
    failures: list[dict] = []
    if args.failures_file and Path(args.failures_file).exists():
        try:
            failures = json.loads(Path(args.failures_file).read_text())
            print(f"Loaded {len(failures)} failures from {args.failures_file}")
        except Exception as exc:
            print(f"Warning: could not parse failures file: {exc}", file=sys.stderr)

    if not failures and args.log_file and Path(args.log_file).exists():
        log_text = Path(args.log_file).read_text()
        failures = parse_failures_from_log(log_text)
        print(f"Parsed {len(failures)} failures from {args.log_file}")

    if not failures and not sys.stdin.isatty():
        stdin_text = sys.stdin.read()
        if stdin_text.strip():
            failures = parse_failures_from_log(stdin_text)
            print(f"Parsed {len(failures)} failures from stdin")

    if not failures:
        print("No failures detected in logs or failures file. Nothing to fix.")
        report_md = "# Automated ATS Link Repair Report\n\nNo failures detected in daily run."
        Path(args.report_file).write_text(report_md)
        return 0

    # 3. Match failures with companies
    targets = []
    for f in failures:
        name = f.get("company_name") or ""
        plat = f.get("ats_platform") or ""
        ident = f.get("ats_identifier") or ""
        c = comp_by_ident.get((plat, ident)) or comp_by_name.get(name.lower())
        if c:
            targets.append({
                "company_name": c["company_name"],
                "ats_platform": c["ats_platform"],
                "ats_identifier": c["ats_identifier"],
                "career_url": c.get("career_url"),
                "error": f.get("error", ""),
            })
        else:
            targets.append({
                "company_name": name,
                "ats_platform": plat,
                "ats_identifier": ident,
                "career_url": f.get("career_url"),
                "error": f.get("error", ""),
            })

    print(f"Attempting link repair for {len(targets)} failed company boards...\n")

    # 4. Probe & verify recoveries
    sem = asyncio.Semaphore(CONCURRENCY)

    async def bounded_recover(client, comp):
        async with sem:
            return await recover_company(client, comp)

    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": UA}, follow_redirects=True) as client:
        recoveries = await asyncio.gather(*(bounded_recover(client, t) for t in targets))

    # 5. Apply fixes to seed/companies.json
    fixed_count = 0
    if not args.dry_run:
        companies, fixed_count = apply_fixes_to_companies(companies, recoveries)
        if fixed_count > 0:
            companies_path.write_text(json.dumps(companies, indent=2) + "\n")
            print(f"Successfully applied {fixed_count} verified fix(es) to {companies_path}.")

            # Optional DB sync
            if args.sync_db:
                try:
                    from db import queries
                    written = queries.upsert_companies(companies)
                    print(f"Synchronized {written} companies to database.")
                except Exception as db_exc:
                    print(f"Note: Database sync skipped/failed: {db_exc}")

    # 6. Generate report
    report_md = generate_report_markdown(recoveries, len(targets))
    Path(args.report_file).write_text(report_md)
    print(f"\nRepair report written to {args.report_file}:")
    print(report_md)

    return 0


def main():
    parser = argparse.ArgumentParser(description="Scan scrape logs, discover & verify ATS fixes.")
    parser.add_argument("--log-file", type=str, default=None,
                        help="path to scrape log output (e.g. scrape.log)")
    parser.add_argument("--failures-file", type=str, default=None,
                        help="path to structured failures JSON")
    parser.add_argument("--companies-file", type=str, default=str(SEED_FILE),
                        help="path to seed/companies.json")
    parser.add_argument("--report-file", type=str, default=str(DEFAULT_REPORT_FILE),
                        help="path to output markdown report")
    parser.add_argument("--dry-run", action="store_true",
                        help="discover and verify fixes without modifying companies.json")
    parser.add_argument("--sync-db", action="store_true",
                        help="sync database directly if connection available")
    args = parser.parse_args()

    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()

