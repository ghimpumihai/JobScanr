"""Shape checks for ``ats_identifier`` values before they are interpolated into request URLs.

Identifiers come from seed/companies.json, which is fed by third-party lists and an LLM-assisted bot PR.
Kept at the top level and standard-library only: the CI seed-validation job installs no dependencies,
and importing anything under ``scrapers/`` would pull in httpx.

Unchecked, a value like ``x@evil.example#`` in the Workday tenant position changes the request host.
"""

import re
from urllib.parse import urlsplit

_SLUG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}")
_TENANT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,99}")
_WD_RE = re.compile(r"wd[0-9]{1,3}")
_SITE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.%-]{0,149}")
_LABEL_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")

SLUG_PLATFORMS = {"greenhouse", "lever", "ashby", "smartrecruiters"}


def identifier_error(platform: str, ident: object) -> str | None:
    """Return a human-readable problem with the identifier, or None if it is acceptable."""
    if not isinstance(ident, str) or not ident or ident != ident.strip():
        return "identifier must be a non-empty string without surrounding whitespace"
    if ".." in ident:
        return "identifier must not contain '..'"
    if platform in SLUG_PLATFORMS:
        if not _SLUG_RE.fullmatch(ident):
            return "identifier must match [A-Za-z0-9][A-Za-z0-9_.-]*"
        return None
    if platform == "workday":
        segments = ident.split("|")
        if len(segments) != 3:
            return "Workday identifier must be tenant|wdN|site"
        tenant, wd, site = segments
        if not _TENANT_RE.fullmatch(tenant) or not _WD_RE.fullmatch(wd) or not _SITE_RE.fullmatch(site):
            return "Workday identifier has an invalid tenant, wdN or site segment"
        return None
    if platform == "teamtailor":
        if ident.lower().startswith(("http://", "https://")):
            parts = urlsplit(ident)
            if parts.scheme != "https" or not parts.hostname or parts.username is not None or parts.password:
                return "Teamtailor URL identifier must be https without credentials"
            return None
        if not _LABEL_RE.fullmatch(ident):
            return "Teamtailor identifier must be a lowercase tenant label or an https URL"
        return None
    return None  # e.g. google: a country list, never placed in a URL path or host
