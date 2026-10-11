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
    """Render personalized 4-section daily digest for a specific user with modern styling."""
    user_email = html.escape(str(user.get("email") or ""))
    submitted = activity.get("submitted_today", [])
    needs_review = activity.get("needs_review", [])
    manual_apply = activity.get("manual_apply", [])

    total_updates = len(submitted) + len(needs_review) + len(manual_apply) + len(unnotified_matches)

    header_html = f"""
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#0f172a;border-radius:8px 8px 0 0;padding:24px 28px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
      <tr>
        <td>
          <table width="100%" cellpadding="0" cellspacing="0">
            <tr>
              <td>
                <span style="display:inline-block;background:#0369a1;color:#e0f2fe;font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase;padding:3px 8px;border-radius:4px;">JobScanr · Daily Digest</span>
                <h1 style="color:#ffffff;font-size:22px;font-weight:700;margin:8px 0 4px 0;line-height:1.2;">Your Career Dispatch</h1>
                <div style="color:#94a3b8;font-size:13px;">Personalized for <strong style="color:#cbd5e1;">{user_email}</strong></div>
              </td>
              <td align="right" style="vertical-align:top;">
                <span style="display:inline-block;background:#1e293b;color:#38bdf8;font-size:13px;font-weight:700;padding:6px 12px;border-radius:20px;border:1px solid #334155;">{total_updates} update{"s" if total_updates != 1 else ""}</span>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
    """

    body_sections = []

    # Section 1: Applications Submitted Today
    if submitted:
        rows = "".join(
            f"""
            <tr style="border-bottom:1px solid #f1f5f9;">
              <td style="padding:10px 12px;color:#0f172a;font-weight:600;font-size:14px;">{html.escape(str(s["title"]))}</td>
              <td style="padding:10px 12px;color:#475569;font-size:13px;">{html.escape(str(s["company_name"]))}</td>
              <td style="padding:10px 12px;text-align:right;">
                <code style="background:#ecfdf5;color:#047857;padding:3px 8px;border-radius:4px;font-size:12px;font-weight:600;border:1px solid #a7f3d0;">{html.escape(str(s["confirmation"]))}</code>
              </td>
            </tr>
            """
            for s in submitted
        )
        body_sections.append(
            f"""
            <div style="margin-bottom:24px;">
              <h3 style="color:#065f46;font-size:15px;font-weight:700;margin:0 0 8px 0;">🚀 Applications Submitted Today ({len(submitted)})</h3>
              <table border="1" cellpadding="6" style="border-collapse:collapse;width:100%;background:#ffffff;border:1px solid #d1fae5;border-radius:6px;overflow:hidden;">
                <tr style="background:#f0fdf4;color:#065f46;font-size:12px;text-transform:uppercase;letter-spacing:0.5px;">
                  <th style="padding:10px 12px;text-align:left;">Role</th>
                  <th style="padding:10px 12px;text-align:left;">Company</th>
                  <th style="padding:10px 12px;text-align:right;">Confirmation</th>
                </tr>
                {rows}
              </table>
            </div>
            """
        )

    # Section 2: Actions Required (needs_review)
    if needs_review:
        rows = "".join(
            f"""
            <tr style="border-bottom:1px solid #fef3c7;">
              <td style="padding:10px 12px;">
                <a href="{html.escape(str(nr.get("url") or ""), quote=True)}" style="color:#0f172a;font-weight:600;font-size:14px;text-decoration:none;">{html.escape(str(nr["title"]))}</a>
              </td>
              <td style="padding:10px 12px;color:#475569;font-size:13px;">{html.escape(str(nr["company_name"]))}</td>
              <td style="padding:10px 12px;text-align:right;">
                <a href="{html.escape(str(nr.get("url") or ""), quote=True)}" style="display:inline-block;background:#d97706;color:#ffffff;font-size:12px;font-weight:600;padding:6px 12px;border-radius:4px;text-decoration:none;">Complete Review &rarr;</a>
              </td>
            </tr>
            """
            for nr in needs_review
        )
        body_sections.append(
            f"""
            <div style="margin-bottom:24px;">
              <h3 style="color:#92400e;font-size:15px;font-weight:700;margin:0 0 6px 0;">⚠️ Actions Required ({len(needs_review)})</h3>
              <p style="color:#78350f;font-size:13px;margin:0 0 10px 0;">These applications need manual input or screening review before submission:</p>
              <table border="1" cellpadding="6" style="border-collapse:collapse;width:100%;background:#ffffff;border:1px solid #fde68a;border-radius:6px;overflow:hidden;">
                <tr style="background:#fffbeb;color:#92400e;font-size:12px;text-transform:uppercase;letter-spacing:0.5px;">
                  <th style="padding:10px 12px;text-align:left;">Role</th>
                  <th style="padding:10px 12px;text-align:left;">Company</th>
                  <th style="padding:10px 12px;text-align:right;">Action</th>
                </tr>
                {rows}
              </table>
            </div>
            """
        )

    # Section 3: 1-Click Manual Apply Roles (Workday & complex portals)
    if manual_apply:
        rows = "".join(
            f"""
            <tr style="border-bottom:1px solid #f1f5f9;">
              <td style="padding:10px 12px;">
                <a href="{html.escape(str(m.get("url") or ""), quote=True)}" style="color:#0f172a;font-weight:600;font-size:14px;text-decoration:none;">{html.escape(str(m["title"]))}</a>
              </td>
              <td style="padding:10px 12px;color:#475569;font-size:13px;">{html.escape(str(m["company_name"]))}</td>
              <td style="padding:10px 12px;color:#64748b;font-size:13px;">{html.escape(str(m.get("location") or ""))}</td>
              <td style="padding:10px 12px;color:#047857;font-weight:600;font-size:12px;">{html.escape(str(m.get("compensation") or ""))}</td>
              <td style="padding:10px 12px;text-align:right;">
                <a href="{html.escape(str(m.get("url") or ""), quote=True)}" style="display:inline-block;background:#4f46e5;color:#ffffff;font-size:12px;font-weight:600;padding:6px 12px;border-radius:4px;text-decoration:none;">Apply &rarr;</a>
              </td>
            </tr>
            """
            for m in manual_apply
        )
        body_sections.append(
            f"""
            <div style="margin-bottom:24px;">
              <h3 style="color:#3730a3;font-size:15px;font-weight:700;margin:0 0 6px 0;">👆 1-Click Manual Apply Roles ({len(manual_apply)})</h3>
              <p style="color:#4338ca;font-size:13px;margin:0 0 10px 0;">Workday and complex ATS portals requiring manual submission:</p>
              <table border="1" cellpadding="6" style="border-collapse:collapse;width:100%;background:#ffffff;border:1px solid #c7d2fe;border-radius:6px;overflow:hidden;">
                <tr style="background:#eef2ff;color:#3730a3;font-size:12px;text-transform:uppercase;letter-spacing:0.5px;">
                  <th style="padding:10px 12px;text-align:left;">Role</th>
                  <th style="padding:10px 12px;text-align:left;">Company</th>
                  <th style="padding:10px 12px;text-align:left;">Location</th>
                  <th style="padding:10px 12px;text-align:left;">Salary</th>
                  <th style="padding:10px 12px;text-align:right;">Action</th>
                </tr>
                {rows}
              </table>
            </div>
            """
        )

    # Section 4: Newly Discovered Matching Postings
    if unnotified_matches:
        body_sections.append(
            f"""
            <div style="margin-bottom:24px;">
              <h3 style="color:#0369a1;font-size:15px;font-weight:700;margin:0 0 12px 0;">✨ Newly Discovered Matching Postings ({len(unnotified_matches)})</h3>
              {build_html_digest(unnotified_matches)}
            </div>
            """
        )

    content_inner = "".join(body_sections)

    footer_html = """
    <div style="padding:20px;background:#f8fafc;border-top:1px solid #e2e8f0;text-align:center;color:#64748b;font-size:12px;">
      <p style="margin:0 0 4px 0;">Generated automatically by <strong>JobScanr</strong>.</p>
      <p style="margin:0;color:#94a3b8;font-size:11px;">To configure your job preferences, update your profile settings.</p>
    </div>
    """

    return f"""
    <div style="max-width:680px;margin:0 auto;background:#ffffff;border:1px solid #cbd5e1;border-radius:10px;overflow:hidden;box-shadow:0 4px 6px -1px rgba(0,0,0,0.05);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
      {header_html}
      <div style="padding:24px 28px;">
        {content_inner}
      </div>
      {footer_html}
    </div>
    """


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

    wrapper_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{html.escape(subject)}</title>
</head>
<body style="margin:0;padding:24px 12px;background-color:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  {html_body}
</body>
</html>"""
    msg.add_alternative(wrapper_html, subtype="html")

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
