"""Delivery channels (plan Phase 7).

FCM: one daily message to topic "job_alerts" — inert until the mobile app
subscribes, kept so the future app works unchanged.
Email: the human-facing channel; phone buzzes, laptop gets clickable links.
"""

import os
import smtplib
from email.message import EmailMessage

import firebase_admin
from firebase_admin import credentials, messaging

from jobs.digest import build_digest

_app = None


def _credentials_path() -> str:
    """Local: FCM_CREDENTIALS_PATH points at the key file.
    CI: FCM_CREDENTIALS_JSON holds the key contents; materialize a tempfile."""
    inline = os.environ.get("FCM_CREDENTIALS_JSON")
    if inline:
        import json
        import tempfile
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


# ── Email ────────────────────────────────────────────────────────────────

def build_html_digest(jobs: list[dict]) -> str:
    rows = "".join(
        f'<tr>'
        f'<td><a href="{j["url"]}">{j["title"]}</a></td>'
        f'<td>{j["company_name"]}</td>'
        f'<td>{j.get("location") or ""}</td>'
        f'</tr>'
        for j in jobs
    )
    return (
        f'<p><strong>{len(jobs)}</strong> new matching job'
        f'{"s" if len(jobs) != 1 else ""}:</p>'
        f'<table border="1" cellpadding="6" style="border-collapse:collapse">'
        f'<tr><th>Role</th><th>Company</th><th>Location</th></tr>'
        f'{rows}</table>'
    )


def send_email_digest(jobs: list[dict]) -> str:
    """Send the digest as HTML mail. Returns the Message-ID header."""
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASS"]
    to_addr = os.environ["DIGEST_EMAIL"]

    summary_title, plain_body = build_digest(jobs)
    msg = EmailMessage()
    msg["Subject"] = f"JobScanr: {summary_title}"
    msg["From"] = user
    msg["To"] = to_addr
    msg.set_content(plain_body + "\n\n(open on laptop; links are in the HTML version)")
    msg.add_alternative(
        f"<html><body>{build_html_digest(jobs)}</body></html>", subtype="html"
    )

    with smtplib.SMTP(host, port) as smtp:
        smtp.starttls()
        smtp.login(user, password)
        smtp.send_message(msg)
    return msg["Message-ID"] or "sent"


def email_configured() -> bool:
    """True when all SMTP settings are present; logs what's missing otherwise."""
    required = ("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "DIGEST_EMAIL")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"Email not configured, skipping (missing: {', '.join(missing)}). "
              f"Set them in .env / Actions secrets to receive digests.")
        return False
    return True
