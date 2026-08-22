"""Shared plumbing for all ATS clients."""

import asyncio
import base64
import html
import re
from abc import ABC, abstractmethod

import httpx

USER_AGENT = "JobScanr/0.1 (personal job alert)"
MAX_RETRIES = 3
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


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
    except Exception:
        return raw


class BaseClient(ABC):
    """One instance per scrape run; reuses the HTTP session across companies."""

    def __init__(self, client: httpx.AsyncClient):
        self.http = client

    @abstractmethod
    async def get_jobs(self, ats_identifier: str) -> list[dict]:
        """Return jobs in the normalized shape:
        {external_id, title, location, department, url, description}
        """

    async def request_with_retry(self, method: str, url: str, **kwargs):
        delay = 0.5
        last_exc: Exception | None = None
        for _ in range(MAX_RETRIES):
            try:
                r = await self.http.request(method, url, **kwargs)
                if r.status_code < 400:
                    return r
                if r.status_code == 404:
                    r.raise_for_status()  # dead board: fail fast, no retry
                if r.status_code != 429 and r.status_code < 500:
                    r.raise_for_status()
            except httpx.HTTPStatusError as exc:
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
