import base64

from scrapers.base import decode_html_field, strip_html


def test_strips_real_tags():
    assert strip_html("<p>Hello <b>world</b></p>") == "Hello world"


def test_unescapes_before_stripping():
    """Greenhouse delivers escaped markup: tags only exist after unescaping."""
    raw = "&lt;h2&gt;Who we are&lt;/h2&gt;\n&lt;p&gt;About us&lt;/p&gt;"
    assert strip_html(raw) == "Who we are About us"


def test_collapses_whitespace():
    assert strip_html("<p>a</p>   \n  <p>b   c</p>") == "a b c"


def test_none_passthrough():
    assert strip_html(None) is None


def test_plain_text_unchanged():
    assert strip_html("just text") == "just text"


def test_decode_base64_roundtrip():
    payload = base64.b64encode("<p>hi</p>".encode()).decode()
    assert decode_html_field(payload) == "<p>hi</p>"


def test_decode_non_base64_passthrough():
    assert decode_html_field("&lt;p&gt;not base64&lt;/p&gt;") == "&lt;p&gt;not base64&lt;/p&gt;"


def test_decode_none_passthrough():
    assert decode_html_field(None) is None


def test_retry_after_sleep_is_capped(monkeypatch):
    import asyncio

    import httpx

    from scrapers.base import BaseClient

    slept: list[float] = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr("scrapers.base.asyncio.sleep", fake_sleep)
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "86400"})
        return httpx.Response(200, json={})

    class Dummy(BaseClient):
        async def get_jobs(self, ats_identifier):
            return []

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            await Dummy(http).request_with_retry("GET", "https://x.test")

    asyncio.run(run())
    assert slept and max(slept) <= 60


def test_workday_alone_gets_openssl_default_ciphers(monkeypatch):
    import ssl

    import httpx

    from scrapers.base import make_http_client

    # Distro Pythons already default to OpenSSL's list, so force CPython's own short list, as in CI.
    real = ssl.create_default_context

    def short_context(*args, **kwargs):
        ctx = real(*args, **kwargs)
        ctx.set_ciphers("ECDH+AESGCM")
        return ctx

    def names(ctx):
        return [c["name"] for c in ctx.get_ciphers()]

    openssl_default = real()
    openssl_default.set_ciphers("DEFAULT")
    monkeypatch.setattr(ssl, "create_default_context", short_context)
    client = make_http_client()

    def tls(url):
        return client._transport_for_url(httpx.URL(url))._pool._ssl_context

    workday = tls("https://acme.wd1.myworkdayjobs.com/wday/cxs/a/b/jobs")
    assert names(workday) == names(openssl_default)
    assert workday.verify_mode == ssl.CERT_REQUIRED and workday.check_hostname
    assert workday.minimum_version == openssl_default.minimum_version
    for other in ("https://boards-api.greenhouse.io/x", "https://notmyworkdayjobs.com/x"):
        assert names(tls(other)) == names(short_context())
