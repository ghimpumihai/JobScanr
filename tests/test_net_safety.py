import asyncio

import httpx
import pytest

import net_safety
from net_safety import UnsafeUrlError, assert_public_url, check_url_syntax, fetch_public


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://10.0.0.5/x",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/",
        "http://[::1]/",
        "http://[fe80::1]/",
        "http://localhost/",
        "http://svc.internal/",
        "http://printer.local/",
        "file:///etc/passwd",
        "gopher://example.com/",
        "https://user:pass@example.com/",
        "https:///nohost",
    ],
)
def test_check_url_syntax_rejects_unsafe(url):
    with pytest.raises(UnsafeUrlError):
        check_url_syntax(url)


def test_check_url_syntax_accepts_public_and_enforces_https():
    assert check_url_syntax("https://jobs.example.com/x") == "jobs.example.com"
    assert check_url_syntax("http://93.184.216.34/") == "93.184.216.34"
    with pytest.raises(UnsafeUrlError):
        check_url_syntax("http://jobs.example.com/", require_https=True)


def _patch_dns(monkeypatch, mapping):
    async def fake(host):
        return mapping[host]

    monkeypatch.setattr(net_safety, "resolve_host_ips", fake)


def test_assert_public_url_blocks_host_resolving_to_private_ip(monkeypatch):
    _patch_dns(monkeypatch, {"rebind.example.com": ["93.184.216.34", "10.0.0.7"], "ok.example.com": ["93.184.216.34"]})
    asyncio.run(assert_public_url("https://ok.example.com/"))
    with pytest.raises(UnsafeUrlError):
        asyncio.run(assert_public_url("https://rebind.example.com/"))


def test_fetch_public_validates_each_redirect_hop(monkeypatch):
    _patch_dns(monkeypatch, {"a.example.com": ["93.184.216.34"], "b.example.com": ["10.1.2.3"]})
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://b.example.com/secret"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await fetch_public(client, "GET", "https://a.example.com/")

    with pytest.raises(UnsafeUrlError):
        asyncio.run(run())
    assert seen == ["https://a.example.com/"]


def test_fetch_public_follows_safe_redirects_and_caps_loops(monkeypatch):
    _patch_dns(monkeypatch, {"a.example.com": ["93.184.216.34"]})

    def ok(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(301, headers={"location": "/final"})
        return httpx.Response(200, text="done")

    def loop(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "/again"})

    async def run(handler):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_public(client, "GET", "https://a.example.com/start")

    assert asyncio.run(run(ok)).text == "done"
    with pytest.raises(UnsafeUrlError):
        asyncio.run(run(loop))
