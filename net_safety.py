"""Guards for server-side fetches of URLs that originate in untrusted third-party data.

Job URLs and pagination links come from ATS responses. Before the backend requests one it must be http(s),
carry no credentials, and not point at loopback / private / link-local / metadata addresses, including
after every redirect hop.

shortcut: DNS is resolved once for the check and again by the HTTP client, so a DNS-rebinding host can
still win the race; upgrade to a pinned-IP transport if the worker ever runs inside a private network.
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx

BLOCKED_HOST_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home.arpa")
MAX_REDIRECTS = 5


class UnsafeUrlError(ValueError):
    """The URL (or a redirect target) is not a public http(s) URL."""


def _is_global_ip(value: str) -> bool:
    try:
        return ipaddress.ip_address(value.split("%", 1)[0]).is_global
    except ValueError:
        return False


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
        return True
    except ValueError:
        return False


def check_url_syntax(url: str, *, require_https: bool = False) -> str:
    """Return the hostname if the URL is a plausible public http(s) URL, else raise UnsafeUrlError.

    Purely static (no DNS): rejects other schemes, credentials, localhost-style names and non-global IP literals.
    """
    try:
        parts = urlsplit(url.strip())
        host = (parts.hostname or "").lower().rstrip(".")
    except ValueError as exc:
        raise UnsafeUrlError(f"unparseable URL: {exc}") from exc
    allowed = ("https",) if require_https else ("http", "https")
    if parts.scheme not in allowed:
        raise UnsafeUrlError(f"scheme {parts.scheme!r} not allowed")
    if not host or parts.username is not None or parts.password is not None:
        raise UnsafeUrlError("missing host or embedded credentials")
    if host == "localhost" or host.endswith(BLOCKED_HOST_SUFFIXES):
        raise UnsafeUrlError("local host name not allowed")
    if _is_ip_literal(host) and not _is_global_ip(host):
        raise UnsafeUrlError("non-public IP address not allowed")
    return host


async def resolve_host_ips(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


async def assert_public_url(url: str) -> None:
    """Raise UnsafeUrlError unless the URL is http(s) and every address its host resolves to is public."""
    host = check_url_syntax(url)
    if _is_ip_literal(host):
        return
    try:
        ips = await resolve_host_ips(host)
    except OSError as exc:
        raise UnsafeUrlError(f"cannot resolve {host}: {exc}") from exc
    if not ips or not all(_is_global_ip(ip) for ip in ips):
        raise UnsafeUrlError(f"{host} resolves to a non-public address")


async def fetch_public(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> httpx.Response:
    """Request ``url`` following redirects manually, validating every hop with assert_public_url."""
    kwargs.pop("follow_redirects", None)
    for _ in range(MAX_REDIRECTS + 1):
        await assert_public_url(url)
        resp = await client.request(method, url, follow_redirects=False, **kwargs)
        location = resp.headers.get("location")
        if resp.is_redirect and location:
            url = urljoin(str(resp.url), location)
            continue
        return resp
    raise UnsafeUrlError("too many redirects")
