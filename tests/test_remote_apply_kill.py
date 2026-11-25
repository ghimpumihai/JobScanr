"""Kill switch for remote apply sessions (#129). Mock transport and mock DB only."""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from db import queries
from scripts import remote_apply_kill
from scripts.remote_apply_kill import close_cloudflare_sessions, release_running_sessions


def test_releases_every_running_session_and_skips_failures():
    seen: list[tuple[str, str, dict | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-BB-API-Key"] == "k"
        body = None if request.method == "GET" else json.loads(request.content)
        seen.append((request.method, str(request.url), body))
        if request.method == "GET":
            return httpx.Response(200, json=[{"id": "a"}, {"id": "b"}])
        return httpx.Response(500 if request.url.path.endswith("/b") else 200, json={})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert release_running_sessions("k", "p", client) == 1
    assert seen[0][:2] == ("GET", "https://api.browserbase.com/v1/sessions?status=RUNNING")
    assert [(m, u) for m, u, _ in seen[1:]] == [
        ("POST", "https://api.browserbase.com/v1/sessions/a"),
        ("POST", "https://api.browserbase.com/v1/sessions/b"),
    ]
    assert seen[1][2] == {"status": "REQUEST_RELEASE", "projectId": "p"}


def test_expire_open_remote_sessions_touches_only_open_rows():
    conn, cur = MagicMock(), MagicMock()
    cur.rowcount = 3
    conn.cursor.return_value.__enter__.return_value = cur
    with patch("db.queries.get_connection") as get_conn:
        get_conn.return_value.__enter__.return_value = conn
        assert queries.expire_open_remote_sessions() == 3
    sql = cur.execute.call_args[0][0]
    assert "SET status = 'expired', ended_at = NOW() WHERE status = 'open'" in sql


@pytest.mark.parametrize(
    "outage",
    [
        httpx.HTTPStatusError("503", request=httpx.Request("GET", "https://x"), response=httpx.Response(503)),
        TypeError("string indices must be integers"),  # a malformed reply, not an HTTP error
    ],
)
def test_one_providers_outage_still_closes_the_other_and_the_rows(monkeypatch, outage):
    for name in (
        "BROWSERBASE_API_KEY",
        "BROWSERBASE_PROJECT_ID",
        "CLOUDFLARE_ACCOUNT_ID",
        "CLOUDFLARE_BROWSER_RUN_TOKEN",
    ):
        monkeypatch.setenv(name, "x")
    monkeypatch.setattr("sys.argv", ["remote_apply_kill"])
    with (
        patch("config.load_environment"),
        patch("scripts.remote_apply_kill.release_running_sessions", side_effect=outage),
        patch("scripts.remote_apply_kill.close_cloudflare_sessions", return_value=2) as cloudflare,
        patch("db.queries.expire_open_remote_sessions", return_value=4) as expire,
    ):
        assert remote_apply_kill.main() == 1  # reports the failure
    cloudflare.assert_called_once()
    expire.assert_called_once()


def test_closes_every_cloudflare_session_with_the_token():
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer tok"
        seen.append((request.method, str(request.url)))
        if request.method == "GET":
            return httpx.Response(200, json=[{"sessionId": "a"}, {"id": "b"}])
        return httpx.Response(200, json={})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert close_cloudflare_sessions("acct", "tok", client) == 2
    base = "https://api.cloudflare.com/client/v4/accounts/acct/browser-run/devtools"
    assert seen == [("GET", f"{base}/session"), ("DELETE", f"{base}/browser/a"), ("DELETE", f"{base}/browser/b")]
