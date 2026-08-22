"""Keyword matching against the hardcoded profile (plan Phase 6)."""

import re

from config import PROFILE

US_RESTRICTED_RE = re.compile(r"\b(united states|usa|u\.s\.|us|canada)\b")


def _normalize(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "")).lower()


def matches_profile(job: dict, profile: dict | None = None) -> bool:
    p = profile or PROFILE
    # Titles and locations are structured fields; descriptions are prose.
    # Matching titles against prose caused false positives ("remote-first
    # culture"), so each signal is checked against its own field.
    headline = f"{_normalize(job.get('title'))} {_normalize(job.get('location'))}"
    text = f"{headline} {_normalize(job.get('description'))}"
    location = _normalize(job.get("location"))

    if not any(t in headline for t in map(_normalize, p["titles"])):
        return False
    if not any(loc in headline for loc in map(_normalize, p["locations"])):
        return False
    # "Remote" alone isn't EU-remote: "Remote - United States" is not
    # applicable. Only count it when the posting doesn't restrict to
    # non-EU countries (and no concrete EU location was named).
    eu_loc_named = any(
        loc != "remote" and loc in location for loc in map(_normalize, p["locations"])
    )
    if "remote" in location and not eu_loc_named and US_RESTRICTED_RE.search(location):
        return False
    if not any(k in text for k in map(_normalize, p["required_keywords"])):
        return False
    if any(k in text for k in map(_normalize, p["excluded_keywords"])):
        return False
    return True
