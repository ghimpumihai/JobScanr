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
