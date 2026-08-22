"""Firebase Cloud Messaging push (plan Phase 7).

One topic ("job_alerts"), one message per day. Test delivery from the
Firebase console before trusting this path.
"""

import json
import os
import tempfile

import firebase_admin
from firebase_admin import credentials, messaging

from jobs.digest import build_digest

_app = None


def _credentials_path() -> str:
    """Local: FCM_CREDENTIALS_PATH points at the key file.
    CI: FCM_CREDENTIALS_JSON holds the key contents; materialize a tempfile."""
    inline = os.environ.get("FCM_CREDENTIALS_JSON")
    if inline:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, prefix="fcm-"
        )
        json.dump(json.loads(inline), tmp)
        tmp.close()
        return tmp.name
    return os.environ.get("FCM_CREDENTIALS_PATH", "fcm-service-account.json")


def _init():
    global _app
    if _app is None:
        _app = firebase_admin.initialize_app(credentials.Certificate(_credentials_path()))
    return _app


def send_digest(jobs: list[dict]) -> str:
    _init()
    title, body = build_digest(jobs)
    message = messaging.Message(
        notification=messaging.Notification(title=title, body=body),
        topic="job_alerts",
    )
    return messaging.send(message)
