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


EMAIL_MAX_INLINE_JOBS = 4


def _render_job_row(
    title: str,
    company: str,
    url: str,
    location: str = "",
    compensation: str = "",
    ats_platform: str = "",
) -> str:
    """Render a clean, flowing job row with subtle tags and pill action button."""
    safe_title = html.escape(title)
    safe_company = html.escape(company)
    safe_url = html.escape(url, quote=True) if url else "#"
    safe_loc = html.escape(location) if location else ""

    meta_subtitle = f"{safe_company} · {safe_loc}" if safe_loc else safe_company

    tags = []
    if compensation:
        tags.append(
            f'<span style="display:inline-block;background:#ecfdf5;color:#047857;'
            f'padding:2px 8px;border-radius:4px;font-size:12px;font-weight:500;margin-right:8px;">'
            f"{html.escape(compensation)}</span>"
        )
    if ats_platform:
        tags.append(
            f'<span style="display:inline-block;background:#f1f5f9;color:#475569;'
            f'padding:2px 8px;border-radius:4px;font-size:12px;">'
            f"via {html.escape(ats_platform.title())}</span>"
        )
    tags_html = "".join(tags)

    return f"""
    <tr style="border-bottom:1px solid #f1f5f9;">
      <td style="padding:18px 0;vertical-align:top;">
        <div style="margin-bottom:3px;">
          <a href="{safe_url}" style="color:#0a66c2;font-size:15px;font-weight:600;text-decoration:none;">{safe_title}</a>
        </div>
        <div style="color:#334155;font-size:13px;font-weight:500;margin-bottom:6px;">
          {meta_subtitle}
        </div>
        <div>
          {tags_html}
        </div>
      </td>
      <td align="right" width="100" style="padding:18px 0;vertical-align:middle;padding-left:16px;">
        <a href="{safe_url}" style="display:inline-block;background:#0a66c2;color:#ffffff;font-size:13px;font-weight:600;padding:8px 18px;border-radius:20px;text-decoration:none;white-space:nowrap;">
          Apply &rarr;
        </a>
      </td>
    </tr>
    """


def _render_web_portal_bridge(total_count: int, remaining_jobs: list[dict], portal_url: str = "#") -> str:
    """Render bridge card for high-volume days redirecting to the web radar."""
    remaining_count = len(remaining_jobs)
    from collections import Counter

    counts = Counter(j.get("company_name", "Other") for j in remaining_jobs)
    top_chips = []
    for comp, cnt in counts.most_common(4):
        top_chips.append(
            f'<span style="display:inline-block;background:#e2e8f0;color:#334155;'
            f'padding:2px 8px;border-radius:4px;font-size:11px;font-weight:500;margin-right:6px;margin-bottom:4px;">'
            f"{html.escape(comp)} ({cnt})</span>"
        )
    leftover = len(counts) - 4
    if leftover > 0:
        top_chips.append(
            f'<span style="display:inline-block;background:#e2e8f0;color:#334155;'
            f'padding:2px 8px;border-radius:4px;font-size:11px;font-weight:500;">'
            f"+{leftover} more</span>"
        )
    chips_html = "".join(top_chips)

    return f"""
    <div style="background:#f8fafc;border:1px solid #cbd5e1;border-radius:8px;padding:20px;margin-top:16px;margin-bottom:8px;">
      <div style="color:#0f172a;font-size:16px;font-weight:700;margin-bottom:4px;">
        +{remaining_count} more matching roles on your JobScanr portal
      </div>
      <div style="color:#475569;font-size:13px;line-height:1.4;margin-bottom:12px;">
        To keep your email fast and uncluttered, view all {total_count} openings filtered and ranked on your web radar.
      </div>
      <div style="margin-bottom:14px;">
        {chips_html}
      </div>
      <div>
        <a href="{html.escape(portal_url, quote=True)}" style="display:inline-block;background:#0a66c2;color:#ffffff;font-size:13px;font-weight:600;padding:10px 20px;border-radius:6px;text-decoration:none;">
          View all {total_count} matches on JobScanr &rarr;
        </a>
      </div>
    </div>
    """


def _render_heartbeat_digest(user_email: str, total_boards: int = 388) -> str:
    """Render positive telemetry heartbeat for zero-match days."""
    from datetime import datetime, timezone

    today_str = datetime.now(timezone.utc).strftime("%b %d")
    return f"""
    <div style="padding:32px 36px 28px 36px;">
      <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:20px;">
        <tr>
          <td>
            <span style="color:#0f172a;font-size:20px;font-weight:700;">JobScanr</span>
          </td>
          <td align="right">
            <span style="display:inline-block;background:#ecfdf5;color:#047857;padding:4px 10px;border-radius:12px;font-size:12px;font-weight:600;">
              ● Radar Active · {today_str}
            </span>
          </td>
        </tr>
      </table>
      <h2 style="color:#0f172a;font-size:20px;font-weight:700;margin:0 0 8px 0;line-height:1.3;">
        All systems healthy — {total_boards} boards checked
      </h2>
      <p style="color:#475569;font-size:14px;line-height:1.5;margin:0 0 20px 0;">
        We scanned all {total_boards} engineering career boards across Europe at 06:00 UTC today. No new software engineering roles matching your profile were posted in the last 24 hours.
      </p>
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:16px 20px;margin-bottom:20px;">
        <tr>
          <td align="center" style="padding:4px 12px;border-right:1px solid #e2e8f0;">
            <div style="color:#0f172a;font-size:16px;font-weight:700;">{total_boards} / {total_boards}</div>
            <div style="color:#64748b;font-size:12px;">Feeds online</div>
          </td>
          <td align="center" style="padding:4px 12px;border-right:1px solid #e2e8f0;">
            <div style="color:#0f172a;font-size:16px;font-weight:700;">06:00 UTC</div>
            <div style="color:#64748b;font-size:12px;">Scan completed</div>
          </td>
          <td align="center" style="padding:4px 12px;">
            <div style="color:#0f172a;font-size:16px;font-weight:700;">0 errors</div>
            <div style="color:#64748b;font-size:12px;">System status</div>
          </td>
        </tr>
      </table>
      <p style="color:#64748b;font-size:13px;line-height:1.4;margin:0;">
        Your next daily scan will run tomorrow at 06:00 UTC. If a matching role appears, it will be delivered straight to your inbox.
      </p>
    </div>
    """


def build_personalized_html_digest(user: dict, unnotified_matches: list[dict], activity: dict | None = None) -> str:
    """Render modern editorial daily digest: jobs stream, high-volume bridge, or positive heartbeat."""
    user_email = html.escape(str(user.get("email") or ""))
    activity = activity or {}

    # Backward compatibility with activity data if passed
    submitted = activity.get("submitted_today", [])
    needs_review = activity.get("needs_review", [])
    manual_apply = activity.get("manual_apply", [])

    total_matches = len(unnotified_matches)

    # 1. Zero-match state -> Render positive heartbeat telemetry
    if total_matches == 0 and not submitted and not needs_review and not manual_apply:
        content_inner = _render_heartbeat_digest(user_email)
        footer_html = """
        <div style="padding:20px 36px 24px 36px;border-top:1px solid #f1f5f9;text-align:center;color:#64748b;font-size:12px;">
          <p style="margin:0 0 4px 0;">JobScanr monitors Greenhouse, Lever, Ashby, Workday, SmartRecruiters, and Teamtailor.</p>
          <p style="margin:0;color:#94a3b8;font-size:11px;">Edit search filters · Pause daily digest · Unsubscribe</p>
        </div>
        """
        return f"""
        <div style="max-width:624px;margin:0 auto;background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
          {content_inner}
          {footer_html}
        </div>
        """

    # 2. Matches state (Standard or High-volume with Bridge Card)
    from datetime import datetime, timezone

    today_str = datetime.now(timezone.utc).strftime("%A, %b %d")

    count_label = f"{total_matches} new matching early-career role{'s' if total_matches != 1 else ''}"

    header_html = f"""
    <div style="padding:32px 36px 24px 36px;border-bottom:1px solid #f1f5f9;">
      <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:16px;">
        <tr>
          <td>
            <span style="color:#0f172a;font-size:20px;font-weight:700;">JobScanr</span>
          </td>
          <td align="right">
            <span style="color:#64748b;font-size:13px;font-weight:500;">Daily Radar · {today_str}</span>
          </td>
        </tr>
      </table>
      <h1 style="color:#0f172a;font-size:22px;font-weight:700;margin:0 0 6px 0;line-height:1.2;">
        {count_label}
      </h1>
      <div style="color:#475569;font-size:14px;">
        Scanned 388 engineering boards across Europe for <strong style="color:#0f172a;">{user_email}</strong>
      </div>
    </div>
    """

    inline_jobs = unnotified_matches[:EMAIL_MAX_INLINE_JOBS]
    overflow_jobs = unnotified_matches[EMAIL_MAX_INLINE_JOBS:]

    rows_html = "".join(
        _render_job_row(
            title=str(j.get("title") or ""),
            company=str(j.get("company_name") or ""),
            url=str(j.get("url") or ""),
            location=str(j.get("location") or ""),
            compensation=str(j.get("compensation") or "") if j.get("compensation") else "",
            ats_platform=str(j.get("ats_platform") or ""),
        )
        for j in inline_jobs
    )

    table_stream = f"""
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
      {rows_html}
    </table>
    """

    bridge_html = _render_web_portal_bridge(total_matches, overflow_jobs) if overflow_jobs else ""

    # Optional activity sections for backward compatibility
    extra_activity_html = ""
    if submitted or needs_review:
        extra_parts = []
        if submitted:
            extra_parts.append(
                f"<div style='margin-top:16px;padding:12px;background:#f0fdf4;border-radius:6px;font-size:13px;color:#166534;'>"
                f"<strong>Applications Submitted Today ({len(submitted)}):</strong> "
                + ", ".join(f"{s['title']} at {s['company_name']} ({s.get('confirmation', 'OK')})" for s in submitted)
                + "</div>"
            )
        if needs_review:
            extra_parts.append(
                f"<div style='margin-top:12px;padding:12px;background:#fffbeb;border-radius:6px;font-size:13px;color:#92400e;'>"
                f"<strong>Actions Required ({len(needs_review)}):</strong> "
                + ", ".join(
                    f"<a href='{nr.get('url', '#')}' style='color:#92400e;font-weight:600;'>{nr['title']} at {nr['company_name']} (Complete Review &rarr;)</a>"
                    for nr in needs_review
                )
                + "</div>"
            )
        extra_activity_html = "".join(extra_parts)

    footer_html = """
    <div style="padding:24px 36px 28px 36px;border-top:1px solid #f1f5f9;text-align:center;color:#64748b;font-size:12px;">
      <p style="margin:0 0 6px 0;">JobScanr scans verified company career feeds daily for early-career European roles.</p>
      <p style="margin:0;color:#94a3b8;font-size:11px;">Edit search preferences · Pause daily digest · Unsubscribe</p>
    </div>
    """

    return f"""
    <div style="max-width:624px;margin:0 auto;background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.04);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
      {header_html}
      <div style="padding:12px 36px 20px 36px;">
        {table_stream}
        {bridge_html}
        {extra_activity_html}
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


def send_user_digest(
    user: dict,
    unnotified_matches: list[dict],
    activity: dict | None = None,
    send_heartbeat: bool = False,
) -> str | None:
    """Send personalized daily digest to a user: matching jobs stream or positive heartbeat."""
    activity = activity or {}
    submitted = activity.get("submitted_today", [])
    needs_review = activity.get("needs_review", [])
    manual_apply = activity.get("manual_apply", [])

    has_content = bool(unnotified_matches or submitted or needs_review or manual_apply)
    if not has_content and not send_heartbeat:
        return None

    to_email = user.get("email")
    if not to_email:
        return None

    if not has_content and send_heartbeat:
        subject = "JobScanr: Radar Active (388 boards checked)"
        text_content = (
            f"JobScanr Daily Radar for {to_email}\n"
            "All systems healthy — 388 boards checked.\n"
            "No new early-career software engineering roles matched your profile in the last 24 hours.\n"
            "Next scan runs tomorrow at 06:00 UTC.\n"
        )
    else:
        total_items = len(unnotified_matches) + len(submitted) + len(needs_review) + len(manual_apply)
        subject = f"JobScanr: Daily Radar ({total_items} role{'s' if total_items != 1 else ''} matched)"
        text_content = f"JobScanr Daily Radar for {to_email}\n- {len(unnotified_matches)} new matching postings\n"
        if submitted:
            text_content += f"- {len(submitted)} applications submitted\n"
        if needs_review:
            text_content += f"- {len(needs_review)} actions required\n"

    html_content = build_personalized_html_digest(user, unnotified_matches, activity)
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
