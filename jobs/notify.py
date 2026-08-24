"""Digest delivery via email (plan Phase 7).

Phone buzzes from the mail app; the laptop gets an HTML table with a
clickable link per role for applying.
"""

import os
import smtplib
from email.message import EmailMessage

from config import DIGEST_EMAIL
from jobs.digest import build_digest


def build_html_digest(jobs: list[dict]) -> str:
    rows = ""
    for j in jobs:
        comp = f'<td>{j["compensation"]}</td>' if j.get("compensation") else "<td></td>"
        deadline = (f'<td>⏳ {j["application_deadline"]}</td>'
                    if j.get("application_deadline") else "<td></td>")
        rows += (
            f'<tr>'
            f'<td><a href="{j["url"]}">{j["title"]}</a></td>'
            f'<td>{j["company_name"]}</td>'
            f'<td>{j.get("location") or ""}</td>'
            f'{comp}{deadline}'
            f'</tr>'
        )
    header = "<tr><th>Role</th><th>Company</th><th>Location</th><th>Salary</th><th>Deadline</th></tr>"
    return (
        f'<p><strong>{len(jobs)}</strong> new matching job'
        f'{"s" if len(jobs) != 1 else ""}:</p>'
        f'<table border="1" cellpadding="6" style="border-collapse:collapse">'
        f'{header}{rows}</table>'
    )


def send_email_digest(jobs: list[dict]) -> str:
    """Send the digest as HTML mail. Returns the Message-ID header."""
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASS"]

    summary_title, plain_body = build_digest(jobs)
    msg = EmailMessage()
    msg["Subject"] = f"JobScanr: {summary_title}"
    msg["From"] = user
    msg["To"] = DIGEST_EMAIL
    msg.set_content(plain_body)
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
    missing = [k for k in required if not os.environ.get(k) and k != "DIGEST_EMAIL"]
    if not DIGEST_EMAIL:
        missing.append("DIGEST_EMAIL (or DIGEST_EMAIL_TEST for staging)")
    if missing:
        print(f"Email not configured, skipping (missing: {', '.join(missing)}). "
              f"Set them in .env / Actions secrets to receive digests.")
        return False
    return True
