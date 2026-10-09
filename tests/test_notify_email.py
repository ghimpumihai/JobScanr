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



def test_html_escaping_prevents_injection():
    job = {
        "title": "<script>alert('xss')</script> Engineer & Developer",
        "company_name": "Acme <Inc>",
        "location": "Berlin & Paris",
        "url": "https://example.com/job?id=1&ref=\"onload=\"evil()",
        "compensation": "<€50k & €60k>",
        "application_deadline": "<2026-12-31>",
    }
    html = build_html_digest([job])
    # Ensure unescaped tags are not present
    assert "<script>" not in html
    assert "<Inc>" not in html
    assert "<€50k" not in html
    assert "<2026-12-31>" not in html
    assert '"onload="evil()' not in html
    # Ensure escaped entities are present
    assert "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt; Engineer &amp; Developer" in html
    assert "Acme &lt;Inc&gt;" in html
    assert "Berlin &amp; Paris" in html
    assert "&lt;€50k &amp; €60k&gt;" in html
    assert "⏳ &lt;2026-12-31&gt;" in html
    assert "href=\"https://example.com/job?id=1&amp;ref=&quot;onload=&quot;evil()\"" in html
from unittest.mock import MagicMock, patch
from jobs.notify import _send_email


def test_send_email_starttls_default(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "user@example.com")
    monkeypatch.setenv("SMTP_PASS", "secret")
    monkeypatch.delenv("SMTP_SSL", raising=False)

    mock_smtp_instance = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_smtp_instance) as mock_smtp,          patch("smtplib.SMTP_SSL") as mock_smtp_ssl:
        mock_smtp_instance.__enter__.return_value = mock_smtp_instance
        _send_email("Subject", "Body", "Body", to_email="test@example.com")

        mock_smtp.assert_called_once_with("smtp.example.com", 587)
        mock_smtp_instance.starttls.assert_called_once()
        mock_smtp_instance.login.assert_called_once_with("user@example.com", "secret")
        mock_smtp_instance.send_message.assert_called_once()
        mock_smtp_ssl.assert_not_called()


def test_send_email_ssl_port_465(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_USER", "user@example.com")
    monkeypatch.setenv("SMTP_PASS", "secret")
    monkeypatch.delenv("SMTP_SSL", raising=False)

    mock_ssl_instance = MagicMock()
    with patch("smtplib.SMTP") as mock_smtp,          patch("smtplib.SMTP_SSL", return_value=mock_ssl_instance) as mock_smtp_ssl:
        mock_ssl_instance.__enter__.return_value = mock_ssl_instance
        _send_email("Subject", "Body", "Body", to_email="test@example.com")

        mock_smtp_ssl.assert_called_once_with("smtp.example.com", 465)
        mock_ssl_instance.login.assert_called_once_with("user@example.com", "secret")
        mock_ssl_instance.send_message.assert_called_once()
        mock_smtp.assert_not_called()


def test_send_email_ssl_env_flag(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_USER", "user@example.com")
    monkeypatch.setenv("SMTP_PASS", "secret")
    monkeypatch.setenv("SMTP_SSL", "true")

    mock_ssl_instance = MagicMock()
    with patch("smtplib.SMTP") as mock_smtp,          patch("smtplib.SMTP_SSL", return_value=mock_ssl_instance) as mock_smtp_ssl:
        mock_ssl_instance.__enter__.return_value = mock_ssl_instance
        _send_email("Subject", "Body", "Body", to_email="test@example.com")

        mock_smtp_ssl.assert_called_once_with("smtp.example.com", 2525)
        mock_ssl_instance.login.assert_called_once_with("user@example.com", "secret")
        mock_ssl_instance.send_message.assert_called_once()
        mock_smtp.assert_not_called()
