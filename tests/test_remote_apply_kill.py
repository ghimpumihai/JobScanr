"""Kill switch for remote apply sessions (#129). Mock transport and mock DB only."""

import json
from unittest.mock import MagicMock, patch

import httpx

from db import queries
from scripts.remote_apply_kill import release_running_sessions


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
