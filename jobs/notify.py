"""Digest delivery via email (plan Phase 7).

Phone buzzes from the mail app; the laptop gets an HTML table with a
clickable link per role for applying.
"""

import os
import smtplib
from email.message import EmailMessage

from config import DIGEST_EMAIL, FIXER_EMAIL
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


def _send_email(subject: str, text_body: str, html_body: str, to_email: str | None = None) -> str:
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASS"]
    recipient = to_email or DIGEST_EMAIL

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = recipient
    msg.set_content(text_body)
    msg.add_alternative(
        f"<html><body>{html_body}</body></html>", subtype="html"
    )

    with smtplib.SMTP(host, port) as smtp:
        smtp.starttls()
        smtp.login(user, password)
        smtp.send_message(msg)
    return msg["Message-ID"] or "sent"


def send_email_digest(jobs: list[dict]) -> str:
    """Send the digest as HTML mail. Returns the Message-ID header."""
    summary_title, plain_body = build_digest(jobs)
    return _send_email(
        subject=f"JobScanr: {summary_title}",
        text_body=plain_body,
        html_body=build_html_digest(jobs),
        to_email=DIGEST_EMAIL,
    )


def build_html_failures_alert(unrecoverable: list[dict]) -> str:
    rows = ""
    for u in unrecoverable:
        comp = u.get("company_name", "Unknown")
        old_plat = u.get("old_platform", "?")
        old_ident = u.get("old_ident", "?")
        ats_str = f"{old_plat}/{old_ident}"
        url = u.get("career_url") or ""
        url_cell = f'<a href="{url}">{url}</a>' if url else "<em>None</em>"
        reason = u.get("reason") or "no live ATS coordinates could be verified"
        rows += (
            f"<tr>"
            f"<td><strong>{comp}</strong></td>"
            f"<td><code>{ats_str}</code></td>"
            f"<td>{url_cell}</td>"
            f"<td>{reason}</td>"
            f"</tr>"
        )
    header = "<tr><th>Company</th><th>Current ATS</th><th>Stored Career URL</th><th>Issue / Reason</th></tr>"
    count = len(unrecoverable)
    return (
        f"<p>JobScanr automated link recovery detected <strong>{count}</strong> "
        f"broken company career link{'s' if count != 1 else ''} that could not be automatically healed and require manual review:</p>"
        f'<table border="1" cellpadding="6" style="border-collapse:collapse">'
        f"{header}{rows}</table>"
        f'<p style="color:#555;font-size:13px;margin-top:12px;">'
        f"Please check the careers page for the above company and update <code>seed/companies.json</code>."
        f"</p>"
    )


def build_text_failures_alert(unrecoverable: list[dict]) -> str:
    count = len(unrecoverable)
    lines = [
        f"JobScanr Alert: {count} broken ATS career link{'s' if count != 1 else ''} could not be automatically resolved today and require manual review:\n"
    ]
    for u in unrecoverable:
        comp = u.get("company_name", "Unknown")
        old_plat = u.get("old_platform", "?")
        old_ident = u.get("old_ident", "?")
        url = u.get("career_url") or "None"
        reason = u.get("reason") or "no live ATS coordinates could be verified"
        lines.append(f"- {comp} ({old_plat}/{old_ident})")
        lines.append(f"  Career URL: {url}")
        lines.append(f"  Issue: {reason}\n")
    lines.append("Please check and update seed/companies.json.")
    return "\n".join(lines)


def send_email_unrecoverable_failures(unrecoverable: list[dict], to_email: str | None = None) -> str:
    """Send alert email to FIXER_EMAIL when broken ATS links cannot be automatically recovered."""
    count = len(unrecoverable)
    subject = f"JobScanr Alert: {count} Broken ATS Career Link{'s' if count != 1 else ''} Need Manual Review"
    recipient = to_email or FIXER_EMAIL
    return _send_email(
        subject=subject,
        text_body=build_text_failures_alert(unrecoverable),
        html_body=build_html_failures_alert(unrecoverable),
        to_email=recipient,
    )


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


def fixer_email_configured() -> bool:
    """True when SMTP settings and FIXER_EMAIL are present; logs what's missing otherwise."""
    required = ("SMTP_HOST", "SMTP_USER", "SMTP_PASS")
    missing = [k for k in required if not os.environ.get(k)]
    if not FIXER_EMAIL:
        missing.append("FIXER_EMAIL (or FIXER_EMAIL_TEST for staging)")
    if missing:
        print(f"Fixer email not configured, skipping (missing: {', '.join(missing)}). "
              f"Set in .env / Actions secrets to receive link repair alerts.")
        return False
    return True
