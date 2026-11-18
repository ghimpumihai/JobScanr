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
