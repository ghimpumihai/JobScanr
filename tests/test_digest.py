from jobs.digest import build_digest


def _job(title):
    return {"title": title, "company_name": "Acme"}


def test_single_job_singular_title():
    title, body = build_digest([_job("Backend Engineer")])
    assert title == "1 new matching job"
    assert body == "Backend Engineer @ Acme"


def test_multiple_jobs_plural_and_more_suffix():
    jobs = [_job(f"Role {i}") for i in range(1, 6)]
    title, body = build_digest(jobs)
    assert title == "5 new matching jobs"
    assert body.startswith("Role 1 @ Acme, Role 2 @ Acme, Role 3 @ Acme")
    assert body.endswith("+2 more")


def test_exactly_three_jobs_no_suffix():
    title, body = build_digest([_job("A"), _job("B"), _job("C")])
    assert title == "3 new matching jobs"
    assert "+" not in body


def test_body_capped_at_200_chars():
    jobs = [_job("X" * 120) for _ in range(4)]
    _, body = build_digest(jobs)
    assert len(body) <= 200
