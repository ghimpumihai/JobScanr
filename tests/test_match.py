import pytest

from jobs.match import matches_profile


@pytest.fixture
def profile():
    return {
        "titles": ["software engineer", "software developer",
                   "software engineering", "software development",
                   "backend", "python"],
        "levels": ["intern", "internship", "working student", "student",
                   "new grad", "new-grad", "graduate", "junior", "associate",
                   "entry level", "entry-level", "trainee"],
        "required_keywords": [],
        "excluded_keywords": ["senior", "sr.", "lead", "manager", "principal", "staff"],
        "excluded_title_keywords": [
            "frontend", "front-end", "mobile", "android", "ios",
            "data scientist", "machine learning", "security",
            "sales engineer", "solutions", "recruiter",
            "site reliability", "devops", "qa", "test engineer",
            "embedded", "hardware",
        ],
        "locations": ["berlin", "amsterdam", "remote", "netherlands", "germany"],
        "eligible_regions": [
            "germany", "netherlands", "berlin", "amsterdam",
            "europe", "european union", "eu",
        ],
    }


# ── level gate: intern / new grad / junior required in the title ─────────

@pytest.mark.parametrize("title", [
    "Software Engineer, Internship",
    "Software Engineering Intern",
    "New Grad Software Engineer",
    "Graduate Software Developer",
    "Junior Backend Engineer",
    "Working Student - Software Development",
    "Associate Software Engineer",
])
def test_early_career_titles_match(profile, title):
    job = {"title": title, "location": "Berlin, Germany",
           "description": "python java whatever"}
    assert matches_profile(job, profile), title


@pytest.mark.parametrize("title", [
    "Software Engineer",                      # no level signal
    "Backend Engineer",                       # no level signal
    "Software Developer",                     # no level signal
])
def test_mid_level_titles_rejected(profile, title):
    job = {"title": title, "location": "Berlin, Germany",
           "description": "python"}
    assert not matches_profile(job, profile), title


# ── role family exclusions still apply ────────────────────────────────────

@pytest.mark.parametrize("title", [
    "Junior Frontend Engineer",
    "Frontend Intern",
    "Junior Data Scientist",
    "Security Engineering Intern",
])
def test_excluded_families_rejected_even_if_junior(profile, title):
    job = {"title": title, "location": "Berlin, Germany",
           "description": "python"}
    assert not matches_profile(job, profile), title


# ── seniority exclusions ─────────────────────────────────────────────────

@pytest.mark.parametrize("title", [
    "Senior Software Engineer, Internship Mentor",
    "Sr. Backend Engineer (Graduate Program Lead)",
    "Software Engineer Manager for Graduates",
])
def test_seniority_rejected(profile, title):
    job = {"title": title, "location": "Berlin", "description": "python"}
    assert not matches_profile(job, profile), title


# ── geography ─────────────────────────────────────────────────────────────

def test_eu_location_matches(profile):
    job = {"title": "Junior Software Engineer",
           "location": "Amsterdam, Netherlands", "description": None}
    assert matches_profile(job, profile)


def test_non_eu_location_rejected(profile):
    job = {"title": "Junior Software Engineer",
           "location": "Tokyo, Japan", "description": "python"}
    assert not matches_profile(job, profile)


@pytest.mark.parametrize("location", [
    "San Francisco, CA, US; Remote, US",
    "Remote - United States",
])
def test_us_remote_rejected(profile, location):
    job = {"title": "Junior Software Engineer", "location": location,
           "description": "python golang"}
    assert not matches_profile(job, profile), location


# ── country-restriction detection in descriptions ────────────────────────

@pytest.mark.parametrize("description", [
    "Great team! Candidates must be based in the United States.",
    "You must be eligible to work in the UK to apply.",
    "Only open to candidates located in Singapore. Python involved.",
    "This role requires work authorization in Japan; python is our stack.",
    "Applicants must have right to work in Canada.",
])
def test_foreign_country_restrictions_rejected(profile, description):
    job = {"title": "Junior Software Engineer",
           "location": "Remote", "description": description}
    assert not matches_profile(job, profile), description


@pytest.mark.parametrize("description", [
    "Candidates must be based in Berlin or willing to relocate.",
    "You must be eligible to work in the European Union.",
    "Open to applicants across Europe; python a plus.",
    # Mentions both regions in one sentence -> not exclusive:
    "This internship is open to students in the US and Europe.",
    "No country restriction; we hire globally for python teams.",
])
def test_compatible_or_unrestricted_descriptions_pass(profile, description):
    job = {"title": "Junior Software Engineer",
           "location": "Remote", "description": description}
    assert matches_profile(job, profile), description


def test_none_fields_do_not_crash(profile):
    job = {"title": None, "location": None, "description": None}
    assert not matches_profile(job, profile)


def test_intern_word_boundary_not_internal(profile):
    """'intern' must not ride on 'internal'."""
    job = {"title": "Software Engineer, Internal Tools",
           "location": "Berlin", "description": "python"}
    assert not matches_profile(job, profile)
