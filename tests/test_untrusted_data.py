import pytest

from jobs.match import matches_profile
from jobs.notify import _safe_href, build_html_digest, build_personalized_html_digest

PAYLOAD = "<img src=x onerror=alert(1)>\"'"


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://jobs.example.com/a?b=1&c=2", "https://jobs.example.com/a?b=1&amp;c=2"),
        ("HTTP://jobs.example.com/", "HTTP://jobs.example.com/"),
        ("javascript:alert(1)", "#"),
        (" JavaScript:alert(1)", "#"),
        ("data:text/html,<script>1</script>", "#"),
        ("vbscript:x", "#"),
        ("//evil.example.com/x", "#"),
        ("", "#"),
        (None, "#"),
    ],
)
def test_safe_href(url, expected):
    assert _safe_href(url) == expected


def test_safe_href_escapes_attribute_breakout():
    out = _safe_href("https://x.example/?q=' onmouseover='alert(1)")
    assert "'" not in out and "onmouseover=" not in out.replace("&#x27; onmouseover=", "")


def test_job_row_digest_neutralizes_javascript_urls():
    html_out = build_html_digest([{"title": "T", "company_name": "C", "location": "L", "url": "javascript:alert(1)"}])
    assert "javascript:" not in html_out and 'href="#"' in html_out


ONE_MATCH = [{"title": "T", "company_name": "C", "location": "L", "url": "https://jobs.example.com/1"}]


def test_activity_sections_escape_scraped_text_and_urls():
    html_out = build_personalized_html_digest(
        {"email": "a@example.com"},
        ONE_MATCH,
        {
            "submitted_today": [{"title": PAYLOAD, "company_name": PAYLOAD, "confirmation": PAYLOAD}],
            "needs_review": [{"title": PAYLOAD, "company_name": PAYLOAD, "url": "x' onmouseover='alert(1)"}],
        },
    )
    assert "<img" not in html_out
    assert "onmouseover='alert" not in html_out
    assert "&lt;img" in html_out


def test_activity_review_link_rejects_javascript_scheme():
    html_out = build_personalized_html_digest(
        {"email": "a@example.com"},
        ONE_MATCH,
        {"needs_review": [{"title": "T", "company_name": "C", "url": "javascript:alert(1)"}]},
    )
    assert "javascript:" not in html_out
    assert "Complete Review" in html_out


BASE = {
    "titles": ["software engineer"],
    "levels": ["junior"],
    "locations": ["berlin"],
    "excluded_title_keywords": [],
}
JOB = {
    "title": "Junior Software Engineer",
    "location": "Berlin",
    "description": "Build things " + "a" * 40,
}


def test_user_regex_invalid_pattern_is_skipped_not_raised():
    assert matches_profile(JOB, {**BASE, "excluded_description_patterns": ["(", "[unclosed"]}) is True


def test_user_regex_valid_pattern_still_excludes():
    assert matches_profile(JOB, {**BASE, "excluded_description_patterns": ["build things"]}) is False


def test_user_regex_bad_types_oversized_and_overcount_are_ignored():
    assert matches_profile(JOB, {**BASE, "excluded_description_patterns": "build things"}) is True  # not a list
    assert matches_profile(JOB, {**BASE, "excluded_description_patterns": [123, None, ["x"]]}) is True
    assert matches_profile(JOB, {**BASE, "excluded_description_patterns": ["a" * 201]}) is True
    many = ["zzz"] * 20 + ["build things"]  # 21st pattern is beyond the cap
    assert matches_profile(JOB, {**BASE, "excluded_description_patterns": many}) is True


def test_missing_profile_keys_do_not_raise():
    assert matches_profile(JOB, {"levels": ["junior"]}) is False  # no titles/locations -> no match, no KeyError
