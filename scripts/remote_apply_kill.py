"""Kill switch for the remote-browser apply spike (#129): release every running Browserbase session in the project
and mark every open session row expired. Set REMOTE_APPLY_ENABLED=false as well, so no new sessions start.

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


def main() -> int:
    config.setup_logging()
    parser = argparse.ArgumentParser(description="Stop every remote apply session (#129).")
    parser.add_argument("--staging", action="store_true", help="use staging environment (.env.stage)")
    args = parser.parse_args()
    config.load_environment(staging=args.staging)

    api_key, project_id = os.environ.get("BROWSERBASE_API_KEY"), os.environ.get("BROWSERBASE_PROJECT_ID")
    released = 0
    if api_key and project_id:
        with httpx.Client() as client:
            released = release_running_sessions(api_key, project_id, client)
    else:
        logger.warning("BROWSERBASE_API_KEY/BROWSERBASE_PROJECT_ID not set; only the database rows are closed.")
    expired = queries.expire_open_remote_sessions()
    logger.info("Released %d Browserbase session(s); marked %d open row(s) expired.", released, expired)
    return 0


if __name__ == "__main__":
    sys.exit(main())
