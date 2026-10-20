"""AI-assisted ATS search and triage module.

Searches DuckDuckGo for failed company career boards, analyzes search snippets
with Groq (Llama 3.3 / GPT-OSS), live-verifies candidate feeds, and triages
unrecoverable links into verified fixes or pruning recommendations.
"""

import json
import logging
import os
import re

import httpx

from scripts.validate_companies import (
    ALIASES,
    CHECKS,
    SIGNATURES,
    construct_career_url,
    has_active_jobs,
)

logger = logging.getLogger(__name__)

VENDOR_SELF_IDENTIFIERS: dict[str, set[str]] = {
    "workday": {"workday"},
    "greenhouse": {"greenhouse", "greenhouseio", "greenhouse-software"},
    "lever": {"lever", "leverco"},
    "ashby": {"ashby", "ashbyhq"},
    "smartrecruiters": {"smartrecruiters"},
    "teamtailor": {"teamtailor"},
}

ALLOWED_SUFFIXES = {
    "hq",
    "careers",
    "career",
    "jobs",
    "job",
    "inc",
    "corp",
    "corporation",
    "tech",
    "technology",
    "technologies",
    "ai",
    "app",
    "io",
    "co",
    "us",
    "uk",
    "eu",
    "group",
    "software",
    "team",
    "global",
    "holdings",
    "llc",
    "ltd",
}

ALLOWED_PREFIXES = {"get", "try", "fly", "use", "join", "meet", "weare", "go"}

GENERIC_WORDS = {
    "global",
    "technologies",
    "technology",
    "solutions",
    "services",
    "systems",
    "group",
    "capital",
    "partners",
    "digital",
    "media",
    "holdings",
    "management",
    "international",
    "software",
    "network",
    "networks",
    "consulting",
    "associates",
    "corporation",
    "company",
    "corp",
    "inc",
    "llc",
    "ltd",
    "health",
}


def _is_slug_match(comp_slug: str, tenant_slug: str) -> bool:
    if comp_slug == tenant_slug:
        return True
    if tenant_slug.startswith(comp_slug) and tenant_slug[len(comp_slug) :] in ALLOWED_SUFFIXES:
        return True
    if comp_slug.startswith(tenant_slug) and comp_slug[len(tenant_slug) :] in ALLOWED_SUFFIXES:
        return True
    for prefix in ALLOWED_PREFIXES:
        if tenant_slug.startswith(prefix) and tenant_slug[len(prefix) :] == comp_slug:
            return True
        if comp_slug.startswith(prefix) and comp_slug[len(prefix) :] == tenant_slug:
            return True
    return False


def is_vendor_self_board(company_name: str, platform: str, ident: str) -> bool:
    """Check if the identifier belongs to the ATS platform vendor itself, not the company."""
    vendor_slugs = VENDOR_SELF_IDENTIFIERS.get(platform, set())
    if not vendor_slugs:
        return False
    target_tenant = ident.split("|")[0].lower() if platform == "workday" else ident.lower()
    target_tenant_slug = re.sub(r"[^a-z0-9]", "", target_tenant)
    comp_slug = re.sub(r"[^a-z0-9]", "", company_name.lower())
    return target_tenant_slug in vendor_slugs and comp_slug not in vendor_slugs


def is_plausible_candidate(company_name: str, platform: str, ident: str) -> bool:
    """Check if an ATS candidate extracted from raw web search reasonably relates to the company."""
    if is_vendor_self_board(company_name, platform, ident):
        return False

    tenant = ident.split("|")[0].lower() if platform == "workday" else ident.lower()
    tenant_slug = re.sub(r"[^a-z0-9]", "", tenant)
    comp_slug = re.sub(r"[^a-z0-9]", "", company_name.lower())

    if not tenant_slug or not comp_slug:
        return False

    if _is_slug_match(comp_slug, tenant_slug):
        return True

    aliases = ALIASES.get(company_name.lower(), [])
    for alias in aliases:
        alias_slug = re.sub(r"[^a-z0-9]", "", alias.lower())
        if alias_slug and _is_slug_match(alias_slug, tenant_slug):
            return True

    words = [re.sub(r"[^a-z0-9]", "", w) for w in company_name.lower().split() if len(w) > 3]
    distinct_words = [w for w in words if w not in GENERIC_WORDS]
    for w in distinct_words:
        if _is_slug_match(w, tenant_slug):
            return True

    return False


UNSUPPORTED_ATS_KEYWORDS = [
    "personio",
    "bamboohr",
    "workable",
    "recruitee",
    "pinpoint",
    "icims",
    "successfactors",
    "talentech",
    "breezy",
    "rippling",
    "oraclecloud",
    "taleo",
    "cornerstone",
    "jobvite",
]

GROQ_MODELS = [
    os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b"),
    "qwen/qwen3.8-27b",
    "llama-3.3-70b-versatile",
]


async def verify_ats(client: httpx.AsyncClient, platform: str, ident: str) -> tuple[bool, str]:
    """Verify live public job feed via platform API."""
    check = CHECKS.get(platform)
    if not check:
        return False, f"unsupported platform {platform}"
    try:
        return await check(client, ident)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def search_duckduckgo(company_name: str, max_results: int = 6) -> list[dict]:
    """Query DuckDuckGo for career board links across supported and general portals."""
    results = []
    seen_urls = set()

    try:
        # Import ddgs or duckduckgo_search
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS  # type: ignore

        ddgs = DDGS()
        queries = [
            f'"{company_name}" jobs site:greenhouse.io OR site:ashbyhq.com OR site:lever.co OR site:myworkdayjobs.com OR site:smartrecruiters.com',
            f'"{company_name}" careers jobs',
        ]

        for query in queries:
            try:
                hits = list(ddgs.text(query, max_results=max_results))
                for h in hits:
                    href = h.get("href") or ""
                    if href and href not in seen_urls:
                        seen_urls.add(href)
                        results.append(
                            {
                                "title": h.get("title", ""),
                                "href": href,
                                "body": h.get("body", ""),
                            }
                        )
            except Exception as exc:
                logger.warning(f"DuckDuckGo search error for query '{query}': {exc}")
                continue

    except Exception as exc:
        logger.warning(f"Failed to initialize DuckDuckGo search: {exc}")

    return results


def extract_ats_candidates_from_results(results: list[dict]) -> list[tuple[str, str, str]]:
    """Scan search results for ATS URL patterns. Returns list of (platform, identifier, url)."""
    candidates = []
    seen = set()

    for item in results:
        text = f"{item.get('href', '')} {item.get('body', '')}"
        for platform, pattern in SIGNATURES:
            for m in pattern.finditer(text):
                if platform == "workday":
                    tenant, wd, site = m.group(1), m.group(2), m.group(3)
                    ident = f"{tenant}|{wd}|{site}"
                else:
                    ident = m.group(1)
                key = (platform, ident)
                if key not in seen:
                    seen.add(key)
                    candidates.append((platform, ident, item.get("href", "")))
    return candidates


def detect_unsupported_ats_in_results(results: list[dict]) -> str | None:
    """Detect if search results predominantly point to an unsupported ATS."""
    for item in results:
        url_and_body = (item.get("href", "") + " " + item.get("body", "")).lower()
        for kw in UNSUPPORTED_ATS_KEYWORDS:
            if kw in url_and_body:
                return kw
    return None


async def analyze_with_groq(
    company_name: str,
    search_results: list[dict],
    old_platform: str | None = None,
    old_ident: str | None = None,
    groq_api_key: str | None = None,
) -> dict | None:
    """Ask Groq LLM to evaluate search results and determine ATS coordinates or unsupported status."""
    api_key = groq_api_key or os.environ.get("GROQ_API_KEY")
    if not api_key:
        return None

    results_text = "\n".join(
        f"- Title: {r.get('title')}\n  URL: {r.get('href')}\n  Snippet: {r.get('body')}" for r in search_results[:8]
    )

    prompt = f"""You are an ATS (Applicant Tracking System) career board researcher.
Task: Determine if the company "{company_name}" has an active, official public job board on one of these SUPPORTED ATS platforms:
- greenhouse (boards.greenhouse.io/<ident> or job-boards.greenhouse.io/<ident>)
- ashby (jobs.ashbyhq.com/<ident>)
- lever (jobs.lever.co/<ident>)
- workday (<tenant>.<wd>.myworkdayjobs.com/<site>)
- smartrecruiters (careers.smartrecruiters.com/<ident>)

Context:
Previous known ATS: {old_platform}/{old_ident} (currently broken/404).

Search results:
{results_text if results_text else "No web search results found."}

Instructions:
1. If the company clearly hosts their public jobs on one of the 5 supported platforms above, return supported_ats_found=true, platform, and identifier.
2. If the company uses an unsupported ATS (such as Personio, BambooHR, Teamtailor, Workable, Recruitee, Pinpoint, iCIMS, SuccessFactors, etc.) or has no public careers board, return supported_ats_found=false, unsupported_ats (name of the platform or 'none'), and a brief explanation in reason.
3. If the results are ambiguous or inconclusive, set supported_ats_found=false and reason="inconclusive".

Respond ONLY with a JSON object matching this schema:
{{
  "supported_ats_found": boolean,
  "platform": "greenhouse" | "ashby" | "lever" | "workday" | "smartrecruiters" | null,
  "identifier": "string or null",
  "career_url": "string or null",
  "unsupported_ats": "string or null",
  "reason": "short explanation"
}}
"""

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=20.0) as http_client:
        for model in GROQ_MODELS:
            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a precise data extraction assistant that only outputs valid JSON.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            }
            try:
                resp = await http_client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers=headers,
                    json=payload,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    return json.loads(content)
                logger.warning(f"Groq model {model} returned HTTP {resp.status_code}: {resp.text[:100]}")
            except Exception as exc:
                logger.warning(f"Groq request failed with model {model}: {exc}")
                continue

    return None


async def triage_company_with_ai(
    client: httpx.AsyncClient,
    company: dict,
    groq_api_key: str | None = None,
) -> dict:
    """Search web & analyze with AI to recover broken ATS link or recommend removal.

    Returns dict with resolution:
      - status: "recovered_by_ai" | "remove" | "unresolved"
    """
    name = company.get("company_name") or company.get("name") or ""
    old_platform = company.get("ats_platform")
    old_ident = company.get("ats_identifier")
    career_url = company.get("career_url") or ""

    res = {
        "company_name": name,
        "old_platform": old_platform,
        "old_ident": old_ident,
        "career_url": career_url,
        "status": "unresolved",
        "new_platform": None,
        "new_ident": None,
        "new_career_url": None,
        "verification_detail": None,
        "reason": None,
    }

    # Step 1: Search DuckDuckGo for the company
    results = search_duckduckgo(name)

    # Step 2: Direct pattern extraction from search hits
    candidates = extract_ats_candidates_from_results(results)
    for plat, ident, hit_url in candidates:
        if plat == old_platform and ident == old_ident:
            continue
        if not is_plausible_candidate(name, plat, ident):
            continue
        ok, detail = await verify_ats(client, plat, ident)
        if ok and has_active_jobs(detail):
            res["status"] = "recovered_by_ai"
            res["new_platform"] = plat
            res["new_ident"] = ident
            res["new_career_url"] = construct_career_url(plat, ident) or hit_url
            res["verification_detail"] = detail
            res["reason"] = f"search pattern verified on {plat}/{ident}"
            return res

    # Step 3: Groq LLM Triage
    llm_analysis = await analyze_with_groq(
        company_name=name,
        search_results=results,
        old_platform=old_platform,
        old_ident=old_ident,
        groq_api_key=groq_api_key,
    )

    if llm_analysis:
        if llm_analysis.get("supported_ats_found") and llm_analysis.get("platform") and llm_analysis.get("identifier"):
            plat = llm_analysis["platform"]
            ident = llm_analysis["identifier"]
            if not is_vendor_self_board(name, plat, ident) and is_plausible_candidate(name, plat, ident):
                ok, detail = await verify_ats(client, plat, ident)
                if ok and has_active_jobs(detail):
                    res["status"] = "recovered_by_ai"
                    res["new_platform"] = plat
                    res["new_ident"] = ident
                    res["new_career_url"] = llm_analysis.get("career_url") or construct_career_url(plat, ident)
                    res["verification_detail"] = detail
                    res["reason"] = f"AI discovered & verified on {plat}/{ident}: {llm_analysis.get('reason', '')}"
                    return res

        # Check if AI identified unsupported ATS (must match known unsupported ATS keywords)
        unsupported = llm_analysis.get("unsupported_ats")
        reason = llm_analysis.get("reason") or "no supported ATS board exists"
        if (
            unsupported
            and unsupported.lower() not in ("none", "null")
            and unsupported.lower() in UNSUPPORTED_ATS_KEYWORDS
        ):
            res["status"] = "remove"
            res["reason"] = f"uses unsupported ATS ({unsupported}): {reason}"
            return res

    # Step 4: Fallback heuristic check on search results for unsupported ATS keywords
    detected_unsupported = detect_unsupported_ats_in_results(results)
    if detected_unsupported:
        res["status"] = "remove"
        res["reason"] = f"search results indicate migration to unsupported ATS ({detected_unsupported})"
        return res

    res["status"] = "unresolved"
    res["reason"] = "no active board found on supported platforms (inconclusive search)"
    return res
