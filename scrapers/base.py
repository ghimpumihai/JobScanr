"""Shared plumbing for all ATS clients."""

import asyncio
import base64
import binascii
import html
import re
from abc import ABC, abstractmethod
from urllib.parse import urlsplit

import httpx

from models import JobPosting

USER_AGENT = "JobScanr/0.1 (personal job alert)"
MAX_RETRIES = 3
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


class BlockedByChallenge(RuntimeError):
    """The host answered with a Cloudflare bot-management challenge (an error status + ``cf-mitigated: challenge``).

    A challenge is not a transient rate limit: retrying cannot pass it, and every retry is more automated
    traffic against a host that has told us to stop. Callers must not retry and must not treat it as a dead
    board (the company is fine; we are being turned away).
    """

    blocked = True


# Consecutive challenges (with no successful request in between) after which a host is skipped for the
# rest of the process. Workday serves tenants from shared pods (wd1, wd5, ...), so the pod is the key.
BLOCK_AFTER_CONSECUTIVE = 5


class _ChallengeTracker:
    def __init__(self) -> None:
        self._streak: dict[str, int] = {}
        self.challenged: set[str] = set()  # hosts that answered with a challenge in this process
        self.answered: set[str] = set()  # hosts that answered normally in this process

    @staticmethod
    def key(url: str) -> str:
        host = (urlsplit(url).hostname or "").lower()
        # tenant.wd1.myworkdayjobs.com -> wd1.myworkdayjobs.com
        return host.split(".", 1)[1] if host.endswith(".myworkdayjobs.com") and host.count(".") >= 3 else host

    def is_blocked(self, key: str) -> bool:
        return self._streak.get(key, 0) >= BLOCK_AFTER_CONSECUTIVE

    def record_block(self, key: str) -> None:
        self._streak[key] = self._streak.get(key, 0) + 1
        self.challenged.add(key)

    def record_ok(self, key: str) -> None:
        self._streak[key] = 0
        self.answered.add(key)

    def block(self, key: str) -> None:
        """Skip ``key`` for this process without sending anything (a persisted back-off is active)."""
        self._streak[key] = BLOCK_AFTER_CONSECUTIVE

    def prime(self, key: str) -> None:
        """One challenge blocks ``key`` for this process (probing a host that challenged us before)."""
        self._streak[key] = BLOCK_AFTER_CONSECUTIVE - 1

    def reset(self) -> None:
        self._streak.clear()
        self.challenged.clear()
        self.answered.clear()


challenge_tracker = _ChallengeTracker()


def strip_html(raw: str | None) -> str | None:
    """Normalize an HTML fragment to clean plain text.

    Unescape BEFORE stripping tags: sources like Greenhouse deliver
    HTML-escaped markup ('&lt;p&gt;'), which only becomes real tags after
    unescaping.
    """
    if raw is None:
        return None
    text = TAG_RE.sub(" ", html.unescape(raw))
    return WS_RE.sub(" ", text).strip()


def decode_html_field(raw: str | None) -> str | None:
    """Some APIs document descriptions as base64-encoded HTML.

    Strict decode: if the payload isn't actually base64 (e.g. Greenhouse now
    returns plain escaped HTML), pass it through untouched.
    """
    if raw is None:
        return None
    try:
        return base64.b64decode(raw, validate=True).decode("utf-8", errors="replace")
    except (binascii.Error, ValueError):
        return raw


class BaseClient(ABC):
    """One instance per scrape run; reuses the HTTP session across companies."""

    def __init__(self, client: httpx.AsyncClient):
        self.http = client

    @abstractmethod
    async def get_jobs(self, ats_identifier: str) -> list[JobPosting]:
        """Return jobs in the normalized shape:
        {external_id, title, location, department, url, description}
        """

    async def request_with_retry(self, method: str, url: str, **kwargs):
        delay = 1.0
        last_exc: Exception | None = None
        host_key = challenge_tracker.key(url)
        if challenge_tracker.is_blocked(host_key):
            raise BlockedByChallenge(f"{host_key} is challenging this client; skipped without a request")
        for attempt in range(5):
            try:
                r = await self.http.request(method, url, **kwargs)
                if r.status_code < 400:
                    challenge_tracker.record_ok(host_key)
                    return r
                if r.headers.get("cf-mitigated", "").lower() == "challenge":  # 429 from Workday, usually 403 elsewhere
                    challenge_tracker.record_block(host_key)
                    raise BlockedByChallenge(f"{host_key} answered with a Cloudflare challenge for {url}")
                if r.status_code == 404:
                    r.raise_for_status()  # dead board: fail fast, no retry
                if r.status_code == 429:
                    retry_after = r.headers.get("Retry-After")
                    # Capped: a hostile or broken Retry-After (e.g. 86400) must not stall the whole run.
                    sleep_time = min(
                        float(retry_after) if retry_after and retry_after.isdigit() else (delay * (attempt + 1)),
                        60.0,
                    )
                    await asyncio.sleep(sleep_time)
                    delay *= 1.5
                    continue
                if r.status_code < 500:
                    r.raise_for_status()
            except httpx.HTTPStatusError:
                raise
            except httpx.HTTPError as exc:  # network-level
                last_exc = exc
            await asyncio.sleep(delay)
            delay *= 2
        raise last_exc or RuntimeError(f"retries exhausted for {url}")


def make_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(20.0),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
        limits=httpx.Limits(max_connections=20),
    )
