"""Keyword matching against the hardcoded profile (plan Phase 6).

Checks, in order of cheapness:
1. title is a target software-engineering flavor
2. title carries an early-career level signal (intern / new grad / junior...)
3. title doesn't belong to an excluded role family
4. location (or title) hits an eligible region
5. description/location don't restrict to a foreign country
6. no excluded seniority word anywhere
"""

import re
import unicodedata

from config import PROFILE

US_RESTRICTED_RE = re.compile(r"\b(united states|usa|u\.s\.|us|canada)\b")

# Countries that, when combined with a restriction phrase, disqualify a
# posting (outside the user's eligible regions: UK and Switzerland are
# eligible hubs, so they are deliberately absent here).
FOREIGN_COUNTRY_RE = re.compile(
    r"\b(united states|usa|u\.s\.|canada|mexico|brazil|argentina|chile|colombia|"
    r"india|pakistan|bangladesh|"
    r"singapore|japan|china|hong kong|taiwan|south korea|korea|israel|"
    r"dubai|uae|saudi arabia|qatar|australia|new zealand|south africa|"
    r"turkey|russia|ukraine|philippines|vietnam|indonesia|malaysia|thailand|"
    r"nigeria|egypt|kenya)\b"
)

# Seniority-by-experience patterns live in descriptions, not titles.
YEARS_EXPERIENCE_RE = re.compile(r"\b(?:[5-9]|1[0-9])\+\s*years?\b")

# Sentence-level phrases that turn a nearby country name into a hard
# eligibility constraint ("must be based in...", "work authorization in...").
RESTRICTION_PHRASE_RE = re.compile(
    r"(?:must|required|only|should)[^.!?\n]{0,80}?(?:be\s+)?"
    r"(?:based|located|resid\w*|living|authorized|entitled|eligible|available)"
    r"|based (?:in|out of)"
    r"|located in"
    r"|\bcitizens?\b|\bnationals?\b"
    r"|work (?:authorization|permit|visa|eligibility)"
    r"|right to work"
    r"|legally \w+ to work"
)

_SENTENCE_SPLIT_RE = re.compile(r"[.!?\n]")


def _normalize(text: str | None) -> str:
    """Lowercase, collapse whitespace, strip diacritics ('Zürich'->'zurich')."""
    text = re.sub(r"\s+", " ", (text or "")).lower()
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def _any_word(tokens: list[str], text: str) -> bool:
    """Word-boundary match so 'intern' can't ride on 'internal'."""
    return any(re.search(rf"\b{re.escape(_normalize(t))}\b", text) for t in tokens)


def _foreign_country_restriction(job: dict, p: dict) -> bool:
    """True if any sentence restricts eligibility to a non-eligible region.

    A sentence naming BOTH a foreign country and an eligible region counts as
    compatible ("remote across the US and Europe" is fine; "based in the US"
    is not).
    """
    eligible = [_normalize(r) for r in p.get("eligible_regions", [])]
    location = _normalize(job.get("location"))
    body = f"{_normalize(job.get('description'))} {location}"

    for sentence in filter(None, map(str.strip, _SENTENCE_SPLIT_RE.split(body))):
        if not RESTRICTION_PHRASE_RE.search(sentence):
            continue
        if not FOREIGN_COUNTRY_RE.search(sentence):
            continue
        if not any(region in sentence for region in eligible):
            return True
    return False


def matches_profile(job: dict, profile: dict | None = None) -> bool:
    p = profile or PROFILE
    # Titles and locations are structured fields; descriptions are prose.
    # Matching titles against prose caused false positives ("remote-first
    # culture"), so each signal is checked against its own field.
    title = _normalize(job.get("title"))
    headline = f"{title} {_normalize(job.get('location'))}"
    text = f"{headline} {_normalize(job.get('description'))}"
    location = _normalize(job.get("location"))

    if not _any_word(p["titles"], title):
        return False
    if not _any_word(p.get("levels", []), title):
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
    if _any_word(p.get("excluded_title_keywords", []), title):
        return False
    required = p.get("required_keywords")
    if required and not any(k in text for k in map(_normalize, required)):
        return False
    if p.get("excluded_keywords") and _any_word(p["excluded_keywords"], text):
        return False
    if any(re.search(pat, text, re.IGNORECASE)
           for pat in p.get("excluded_description_patterns", [])):
        return False
    if YEARS_EXPERIENCE_RE.search(text):
        return False
    if _foreign_country_restriction(job, p):
        return False
    return True
