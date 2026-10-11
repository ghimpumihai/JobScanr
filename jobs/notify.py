"""Digest delivery via email (plan Phase 7).

Phone buzzes from the mail app; the laptop gets an HTML table with a
clickable link per role for applying.
"""

import html
import logging
import os
import smtplib
from email.message import EmailMessage

from config import DIGEST_EMAIL
from jobs.digest import build_digest

logger = logging.getLogger(__name__)


def build_html_digest(jobs: list[dict]) -> str:
    rows = ""
    for j in jobs:
        title = html.escape(str(j.get("title") or ""))
        company = html.escape(str(j.get("company_name") or ""))
        location = html.escape(str(j.get("location") or ""))
        url = html.escape(str(j.get("url") or ""), quote=True)
        comp_val = html.escape(str(j["compensation"])) if j.get("compensation") else ""
        comp = f"<td>{comp_val}</td>" if comp_val else "<td></td>"
        deadline_val = html.escape(str(j["application_deadline"])) if j.get("application_deadline") else ""
        deadline = f"<td>⏳ {deadline_val}</td>" if deadline_val else "<td></td>"
        rows += f'<tr><td><a href="{url}">{title}</a></td><td>{company}</td><td>{location}</td>{comp}{deadline}</tr>'
    header = "<tr><th>Role</th><th>Company</th><th>Location</th><th>Salary</th><th>Deadline</th></tr>"
    return (
        f"<p><strong>{len(jobs)}</strong> new matching job"
        f"{'s' if len(jobs) != 1 else ''}:</p>"
        f'<table border="1" cellpadding="6" style="border-collapse:collapse">'
        f"{header}{rows}</table>"
    )


def build_personalized_html_digest(user: dict, unnotified_matches: list[dict], activity: dict) -> str:
    """Render personalized 4-section daily digest for a specific user."""
    sections = []
    user_email = html.escape(str(user.get("email") or ""))
    sections.append(f"<h2>JobScanr Daily Digest for {user_email}</h2>")

    # Section 1: Applications Submitted Today
    submitted = activity.get("submitted_today", [])
    if submitted:
        rows = "".join(
            f"<tr><td>{html.escape(str(s['title']))}</td><td>{html.escape(str(s['company_name']))}</td>"
            f"<td><code>{html.escape(str(s['confirmation']))}</code></td></tr>"
            for s in submitted
        )
        sections.append(
            f"<h3>🚀 Applications Submitted Today ({len(submitted)})</h3>"
            f'<table border="1" cellpadding="6" style="border-collapse:collapse">'
            f"<tr><th>Role</th><th>Company</th><th>Confirmation</th></tr>{rows}</table>"
        )

    # Section 2: Actions Required (needs_review)
    needs_review = activity.get("needs_review", [])
    if needs_review:
        rows = "".join(
            f'<tr><td><a href="{html.escape(str(nr.get("url") or ""), quote=True)}">{html.escape(str(nr["title"]))}</a></td>'
            f"<td>{html.escape(str(nr['company_name']))}</td>"
            f'<td><a href="{html.escape(str(nr.get("url") or ""), quote=True)}">Complete Review &rarr;</a></td></tr>'
            for nr in needs_review
        )
        sections.append(
            f"<h3>⚠️ Actions Required ({len(needs_review)})</h3>"
            f"<p>These applications need manual input or screening review before submission:</p>"
            f'<table border="1" cellpadding="6" style="border-collapse:collapse">'
            f"<tr><th>Role</th><th>Company</th><th>Action</th></tr>{rows}</table>"
        )

    # Section 3: 1-Click Manual Apply Roles (Workday & complex portals)
    manual_apply = activity.get("manual_apply", [])
    if manual_apply:
        rows = "".join(
            f'<tr><td><a href="{html.escape(str(m.get("url") or ""), quote=True)}">{html.escape(str(m["title"]))}</a></td>'
            f"<td>{html.escape(str(m['company_name']))}</td><td>{html.escape(str(m.get('location') or ''))}</td>"
            f"<td>{html.escape(str(m.get('compensation') or ''))}</td>"
            f'<td><a href="{html.escape(str(m.get("url") or ""), quote=True)}">Apply &rarr;</a></td></tr>'
            for m in manual_apply
        )
        sections.append(
            f"<h3>👆 1-Click Manual Apply Roles ({len(manual_apply)})</h3>"
            f"<p>Workday and complex ATS portals requiring manual submission:</p>"
            f'<table border="1" cellpadding="6" style="border-collapse:collapse">'
            f"<tr><th>Role</th><th>Company</th><th>Location</th><th>Salary</th><th>Action</th></tr>{rows}</table>"
        )

    # Section 4: Newly Discovered Matching Postings
    if unnotified_matches:
        sections.append(f"<h3>✨ Newly Discovered Matching Postings ({len(unnotified_matches)})</h3>")
        sections.append(build_html_digest(unnotified_matches))

    return "".join(sections)


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
    msg.add_alternative(f"<html><body>{html_body}</body></html>", subtype="html")

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


def send_user_digest(user: dict, unnotified_matches: list[dict], activity: dict) -> str | None:
    """Send personalized daily digest to a user if there is anything to report."""
    submitted = activity.get("submitted_today", [])
    needs_review = activity.get("needs_review", [])
    manual_apply = activity.get("manual_apply", [])
    if not unnotified_matches and not submitted and not needs_review and not manual_apply:
        return None

    to_email = user.get("email")
    if not to_email:
        return None

    total_items = len(unnotified_matches) + len(submitted) + len(needs_review) + len(manual_apply)
    subject = f"JobScanr: Daily Digest ({total_items} update{'s' if total_items != 1 else ''})"

    html_content = build_personalized_html_digest(user, unnotified_matches, activity)
    text_content = (
        f"JobScanr Daily Digest for {to_email}\n"
        f"- {len(submitted)} applications submitted today\n"
        f"- {len(needs_review)} actions required\n"
        f"- {len(manual_apply)} manual apply roles\n"
        f"- {len(unnotified_matches)} new matching postings\n"
    )
    return _send_email(
        subject=subject,
        text_body=text_content,
        html_body=html_content,
        to_email=to_email,
    )


def email_configured() -> bool:
    """True when all SMTP settings are present; logs what's missing otherwise."""
    required = ("SMTP_HOST", "SMTP_USER", "SMTP_PASS", "DIGEST_EMAIL")
    missing = [k for k in required if not os.environ.get(k) and k != "DIGEST_EMAIL"]
    if not DIGEST_EMAIL:
        missing.append("DIGEST_EMAIL (or DIGEST_EMAIL_TEST for staging)")
    if missing:
        logger.warning(
            "Email not configured, skipping (missing: %s). Set them in .env / Actions secrets to receive digests.",
            ", ".join(missing),
        )
        return False
    return True
