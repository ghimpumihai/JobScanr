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
