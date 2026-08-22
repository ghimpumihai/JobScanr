import pytest

from jobs.match import matches_profile


@pytest.fixture
def profile():
    return {
        "titles": ["backend engineer", "software engineer", "python developer"],
        "required_keywords": ["python"],
        "excluded_keywords": ["senior", "lead", "manager", "principal", "staff"],
        "locations": ["berlin", "amsterdam", "remote", "netherlands", "germany"],
    }


def test_eu_onsite_match(profile):
    job = {"title": "Software Engineer - Fullstack",
           "location": "Amsterdam, Netherlands",
           "description": "You know python well."}
    assert matches_profile(job, profile)


def test_eu_remote_match(profile):
    job = {"title": "Backend Engineer",
           "location": "Remote",
           "description": "python and django"}
    assert matches_profile(job, profile)


def test_location_matched_from_title_field(profile):
    job = {"title": "Backend Engineer (Berlin)",
           "location": None,
           "description": "python"}
    assert matches_profile(job, profile)


@pytest.mark.parametrize("location", [
    "San Francisco, CA, US; Remote, US",
    "Remote - United States",
    "Remote - US",
    "Chicago, IL, US (Remote)",
])
def test_us_restricted_remote_rejected(profile, location):
    job = {"title": "Software Engineer", "location": location,
           "description": "python golang"}
    assert not matches_profile(job, profile), location


def test_non_eu_location_without_remote_rejected(profile):
    job = {"title": "Software Engineer",
           "location": "Tokyo, Japan",
           "description": "lots of python"}
    assert not matches_profile(job, profile)


def test_title_mismatch_rejected(profile):
    job = {"title": "Data Analyst",
           "location": "Berlin, Germany",
           "description": "sql python dashboards"}
    assert not matches_profile(job, profile)


def test_missing_required_keyword_rejected(profile):
    job = {"title": "Backend Engineer",
           "location": "Berlin, Germany",
           "description": "java kotlin spring"}
    assert not matches_profile(job, profile)


def test_excluded_title_keyword_rejected(profile):
    job = {"title": "Senior Software Engineer",
           "location": "Berlin, Germany",
           "description": "python everywhere"}
    assert not matches_profile(job, profile)


def test_excluded_keyword_in_description_rejected(profile):
    job = {"title": "Software Engineer",
           "location": "Berlin, Germany",
           "description": "python; you would lead a small team as team lead"}
    assert not matches_profile(job, profile)


def test_case_insensitive_matching(profile):
    job = {"title": "BACKEND ENGINEER",
           "location": "BERLIN, GERMANY",
           "description": "Python 3.12 microservices"}
    assert matches_profile(job, profile)


def test_none_fields_do_not_crash(profile):
    job = {"title": None, "location": None, "description": None}
    assert not matches_profile(job, profile)


def test_missing_description_still_matches_on_headline(profile):
    """Ashby listings carry no description: title/location must suffice."""
    job = {"title": "Python Developer", "location": "Remote", "description": None}
    assert matches_profile(job, profile)
