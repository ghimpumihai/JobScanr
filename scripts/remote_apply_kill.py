"""Kill switch for the remote-browser apply spike (#129): close every running Browserbase and Cloudflare Browser Run
session and mark every open session row expired. Set REMOTE_APPLY_ENABLED=false as well, so no new sessions start.

Usage:
  python -m scripts.remote_apply_kill            # production (.env)
  python -m scripts.remote_apply_kill --staging  # staging (.env.stage)
"""

import argparse
import logging
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from db import queries

logger = logging.getLogger(__name__)
API = "https://api.browserbase.com/v1"
CLOUDFLARE = "https://api.cloudflare.com/client/v4/accounts/{account}/browser-run/devtools"


def release_running_sessions(api_key: str, project_id: str, client: httpx.Client) -> int:
    """Release every RUNNING session; returns how many were released. A failed release is logged and skipped."""
    headers = {"X-BB-API-Key": api_key}
    resp = client.get(f"{API}/sessions", params={"status": "RUNNING"}, headers=headers, timeout=30)
    resp.raise_for_status()
    released = 0
    for s in resp.json():
        r = client.post(
            f"{API}/sessions/{s['id']}",
            json={"status": "REQUEST_RELEASE", "projectId": project_id},
            headers=headers,
            timeout=30,
        )
        if r.is_success:
            released += 1
        else:
            logger.warning("Could not release session %s: HTTP %s", s["id"], r.status_code)
    return released


def close_cloudflare_sessions(account_id: str, token: str, client: httpx.Client) -> int:
    """Close every active Browser Run session; returns how many were closed. A failed close is logged and skipped."""
    base = CLOUDFLARE.format(account=account_id)
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.get(f"{base}/session", headers=headers, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    sessions = body if isinstance(body, list) else body.get("sessions") or body.get("result") or []
    closed = 0
    for s in sessions:
        sid = s if isinstance(s, str) else s.get("sessionId") or s.get("id")
        r = client.delete(f"{base}/browser/{sid}", headers=headers, timeout=30)
        if r.is_success:
            closed += 1
        else:
            logger.warning("Could not close Cloudflare session %s: HTTP %s", sid, r.status_code)
    return closed


def main() -> int:
    config.setup_logging()
    parser = argparse.ArgumentParser(description="Stop every remote apply session (#129).")
    parser.add_argument("--staging", action="store_true", help="use staging environment (.env.stage)")
    args = parser.parse_args()
    config.load_environment(staging=args.staging)

    api_key, project_id = os.environ.get("BROWSERBASE_API_KEY"), os.environ.get("BROWSERBASE_PROJECT_ID")
    cf_account, cf_token = os.environ.get("CLOUDFLARE_ACCOUNT_ID"), os.environ.get("CLOUDFLARE_BROWSER_RUN_TOKEN")
    released = closed = 0
    failed = False
    # One provider's outage must not stop the other provider or the database rows from being closed.
    with httpx.Client() as client:
        if api_key and project_id:
            try:
                released = release_running_sessions(api_key, project_id, client)
            except Exception as exc:  # also a malformed reply (KeyError, TypeError, ValueError), not only HTTP errors
                failed = True
                logger.error("Browserbase sessions not closed: %s", type(exc).__name__)
        else:
            logger.warning("BROWSERBASE_API_KEY/BROWSERBASE_PROJECT_ID not set; Browserbase skipped.")
        if cf_account and cf_token:
            try:
                closed = close_cloudflare_sessions(cf_account, cf_token, client)
            except Exception as exc:  # as above
                failed = True
                logger.error("Cloudflare sessions not closed: %s", type(exc).__name__)
        else:
            logger.warning("CLOUDFLARE_ACCOUNT_ID/CLOUDFLARE_BROWSER_RUN_TOKEN not set; Cloudflare skipped.")
    expired = queries.expire_open_remote_sessions()
    logger.info(
        "Released %d Browserbase and %d Cloudflare session(s); marked %d open row(s) expired.",
        released,
        closed,
        expired,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
