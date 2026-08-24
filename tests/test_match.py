import pytest

from jobs.match import matches_profile


@pytest.fixture
def profile():
    return {
        "titles": [
            "software engineer", "software developer",
            "software engineering intern", "junior software engineer",
            "junior developer", "graduate software engineer",
            "new grad software engineer", "entry level software engineer",
            "associate software engineer",
        ],
        "levels": ["intern", "internship", "junior", "graduate", "new grad",
                   "new-grad", "entry level", "entry-level", "associate",
                   "trainee", "apprentice"],
        "excluded_title_keywords": [
            "senior", "sr.", "staff", "principal", "lead", "manager",
            "director", "head of", "vp", "vice president", "architect",
            "frontend", "front-end", "mobile", "android", "ios",
            "data scientist", "machine learning", "security",
            "sales engineer", "solutions", "recruiter",
            "site reliability", "devops", "qa", "test engineer",
            "embedded", "hardware",
        ],
        "locations": ["remote", "europe", "berlin", "amsterdam", "london",
                      "paris", "barcelona", "stockholm", "dublin", "lisbon",
                      "warsaw", "prague", "vienna", "zurich", "munich",
                      "brussels", "milan", "bucharest", "budapest"],
        "eligible_regions": [
            "europe", "european union", "eu",
            "germany", "berlin", "munich", "netherlands", "amsterdam",
            "united kingdom", "uk", "england", "london", "switzerland",
            "zurich", "france", "paris", "spain", "barcelona", "sweden",
            "stockholm", "ireland", "dublin", "portugal", "lisbon", "poland",
            "warsaw", "czech republic", "czechia", "prague", "austria",
            "vienna", "belgium", "brussels", "italy", "milan", "romania",
            "bucharest", "hungary", "budapest",
        ],
    }


# ── titles + levels ───────────────────────────────────────────────────────

@pytest.mark.parametrize("title,location", [
    ("Software Engineer Intern", "Berlin, Germany"),
    ("Junior Software Engineer", "Amsterdam, Netherlands"),
    ("Junior Developer", "London, UK"),
    ("Graduate Software Engineer", "Paris, France"),
    ("New Grad Software Engineer", "Remote"),
    ("Entry Level Software Engineer", "Dublin, Ireland"),
    ("Associate Software Engineer", "Zurich, Switzerland"),
    ("Software Engineering Intern", "Stockholm, Sweden"),
    ("Trainee Software Developer", "Barcelona, Spain"),
    ("Apprentice Software Engineer", "Vienna, Austria"),
])
def test_spec_titles_match(profile, title, location):
    job = {"title": title, "location": location,
           "description": "python java whatever"}
    assert matches_profile(job, profile), title


@pytest.mark.parametrize("title", [
    "Software Engineer",          # no level signal
    "Software Developer",         # no level signal
    "Backend Engineer",           # not in title allowlist
    "Data Engineer",              # not in title allowlist
])
def test_missing_level_or_title_rejected(profile, title):
    job = {"title": title, "location": "Berlin, Germany", "description": "python"}
    assert not matches_profile(job, profile), title


# ── exclusions ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("title", [
    "Senior Software Engineer Intern",
    "Staff Software Engineer, University Graduates",
    "Principal Junior?? no — Principal Software Engineer",
    "Software Engineer Lead for Graduates",
    "Engineering Manager, Early Careers",
    "Director of Software Engineering",
    "Head of Software Engineering",
    "VP, Software Engineering",
    "Vice President Software Engineering",
    "Software Architect (Graduate Program)",
    "Junior Frontend Engineer",
    "Front-End Intern",
    "Software Engineer Intern - Mobile",
])
def test_excluded_titles_rejected(profile, title):
    job = {"title": title, "location": "Berlin, Germany",
           "description": "python"}
    assert not matches_profile(job, profile), title


def test_intern_word_boundary_not_internal(profile):
    job = {"title": "Software Engineer, Internal Tools",
           "location": "Berlin", "description": "python"}
    assert not matches_profile(job, profile)


# ── years-of-experience patterns in descriptions ─────────────────────────

@pytest.mark.parametrize("years", ["5+ years", "7+ years", "10+ years"])
def test_experience_requirements_rejected(profile, years):
    job = {"title": "Junior Software Engineer",
           "location": "Berlin, Germany",
           "description": f"Requirements: {years} of professional experience."}
    assert not matches_profile(job, profile), years


def test_low_experience_requirement_passes(profile):
    job = {"title": "Junior Software Engineer",
           "location": "Berlin, Germany",
           "description": "0-2 years of experience; python is a plus."}
    assert matches_profile(job, profile)


# ── geography ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("location", [
    "Remote",
    "Europe (Remote)",
    "Berlin, Germany",
    "London, United Kingdom",
    "Zurich, Switzerland",
    "Warsaw, Poland",
])
def test_eligible_locations_match(profile, location):
    job = {"title": "Junior Software Engineer",
           "location": location, "description": None}
    assert matches_profile(job, profile), location


@pytest.mark.parametrize("location", [
    "Tokyo, Japan",
    "New York, NY",
])
def test_foreign_locations_rejected(profile, location):
    job = {"title": "Junior Software Engineer",
           "location": location, "description": "python"}
    assert not matches_profile(job, profile), location


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
    "Only open to candidates located in Singapore. Python involved.",
    "This role requires work authorization in Japan.",
    "Applicants must have right to work in Canada.",
])
def test_foreign_country_restrictions_rejected(profile, description):
    job = {"title": "Junior Software Engineer",
           "location": "Remote", "description": description}
    assert not matches_profile(job, profile), description


@pytest.mark.parametrize("description", [
    "Candidates must be based in Berlin or willing to relocate.",
    "You must be eligible to work in the European Union.",
    # UK and Switzerland are eligible hubs now:
    "Applicants must have the right to work in the UK.",
    "Must be based in Zurich or London. Python involved.",
    # Names both regions -> not exclusive:
    "This internship is open to students in the US and Europe.",
    "No country restriction; we hire globally.",
])
def test_compatible_descriptions_pass(profile, description):
    job = {"title": "Junior Software Engineer",
           "location": "Remote", "description": description}
    assert matches_profile(job, profile), description


# ── robustness ────────────────────────────────────────────────────────────

def test_none_fields_do_not_crash(profile):
    job = {"title": None, "location": None, "description": None}
    assert not matches_profile(job, profile)

def test_evergreen_ghost_listings_rejected(profile):
    profile = {**profile, "excluded_description_patterns": [
        r"this (exact )?(role|posting|requisition) may not be",
        r"advertis\w+ (a )?potential",
    ]}
    ghost = {"title": "Junior Software Engineer", "location": "Stockholm",
             "description": "This posting is to advertise potential job opportunities. "
                            "This exact role may not be open today."}
    assert not matches_profile(ghost, profile)
    real = {"title": "Junior Software Engineer", "location": "Stockholm",
            "description": "Great growth potential in a real team. Start immediately."}
    assert matches_profile(real, profile)
