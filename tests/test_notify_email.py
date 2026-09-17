from jobs.notify import build_html_digest


def _job(title, url="https://example.com/job"):
    return {"title": title, "company_name": "Acme",
            "location": "Berlin", "url": url}


def test_html_contains_link_per_job():
    html = build_html_digest([_job("Backend Engineer", "https://jobs.example/1"),
                              _job("Junior Developer", "https://jobs.example/2")])
    assert 'href="https://jobs.example/1"' in html
    assert 'href="https://jobs.example/2"' in html
    assert "Backend Engineer" in html and "Junior Developer" in html


def test_html_singular_plural():
    one = build_html_digest([_job("A")])
    many = build_html_digest([_job("A"), _job("B")])
    assert "<strong>1</strong> new matching job:" in one
    assert "<strong>2</strong> new matching jobs:" in many


def test_none_location_renders_empty():
    job = _job("X")
    job["location"] = None
    html = build_html_digest([job])
    assert "<td></td>" in html

def test_salary_and_deadline_columns_render_when_present():
    job = {"title": "A", "company_name": "C", "location": "Berlin",
           "url": "https://x/1", "compensation": "€50k–€60k",
           "application_deadline": "2026-09-30"}
    html = build_html_digest([job])
    assert "<th>Salary</th>" in html and "<th>Deadline</th>" in html
    assert "€50k–€60k" in html and "⏳ 2026-09-30" in html


def test_missing_salary_renders_empty_cells():
    html = build_html_digest([_job("B")])
    assert "<td></td><td></td></tr>" in html


def test_failures_alert_html_and_text():
    from jobs.notify import build_html_failures_alert, build_text_failures_alert

    failures = [
        {
            "company_name": "Postman",
            "old_platform": "greenhouse",
            "old_ident": "postman",
            "career_url": "https://boards.greenhouse.io/postman",
            "reason": "no live ATS coordinates could be verified",
        },
        {
            "company_name": "Acme",
            "old_platform": "lever",
            "old_ident": "acme",
            "career_url": "",
            "reason": "HTTP 404",
        },
    ]

    html = build_html_failures_alert(failures)
    assert "Postman" in html
    assert "greenhouse/postman" in html
    assert "https://boards.greenhouse.io/postman" in html
    assert "no live ATS coordinates could be verified" in html
    assert "Acme" in html
    assert "<em>None</em>" in html

    text = build_text_failures_alert(failures)
    assert "Postman (greenhouse/postman)" in text
    assert "https://boards.greenhouse.io/postman" in text
    assert "Acme (lever/acme)" in text


def test_send_email_unrecoverable_failures(monkeypatch):
    from unittest.mock import MagicMock, patch
    from jobs.notify import send_email_unrecoverable_failures

    monkeypatch.setenv("SMTP_HOST", "smtp.test.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "sender@test.com")
    monkeypatch.setenv("SMTP_PASS", "password123")
    monkeypatch.setattr("jobs.notify.FIXER_EMAIL", "fixer@test.com")

    mock_smtp_instance = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_smtp_instance):
        mock_smtp_instance.__enter__.return_value = mock_smtp_instance
        res = send_email_unrecoverable_failures([
            {
                "company_name": "Postman",
                "old_platform": "greenhouse",
                "old_ident": "postman",
                "career_url": "https://boards.greenhouse.io/postman",
                "reason": "no live ATS coordinates could be verified",
            }
        ])
        assert mock_smtp_instance.starttls.called
        assert mock_smtp_instance.login.called
        assert mock_smtp_instance.send_message.called
        sent_msg = mock_smtp_instance.send_message.call_args[0][0]
        assert sent_msg["To"] == "fixer@test.com"
        assert "JobScanr Alert" in sent_msg["Subject"]


def test_fixer_email_configured(monkeypatch):
    from jobs.notify import fixer_email_configured

    monkeypatch.setenv("SMTP_HOST", "smtp.test.com")
    monkeypatch.setenv("SMTP_USER", "sender@test.com")
    monkeypatch.setenv("SMTP_PASS", "password123")
    monkeypatch.setattr("jobs.notify.FIXER_EMAIL", "fixer@test.com")
    assert fixer_email_configured() is True

    monkeypatch.setattr("jobs.notify.FIXER_EMAIL", "")
    assert fixer_email_configured() is False

