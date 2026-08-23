"""Central config: hardcoded user profile + env-driven secrets."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# DB routing: experiments and smoke tests should never write into the
# production archive. Set DB_ENV=staging (plus DATABASE_URL_STAGING in
# .env) to point every query at the staging project instead.
DB_ENV = os.environ.get("DB_ENV", "production").strip().lower()
if DB_ENV not in ("production", "staging"):
    DB_ENV = "production"
# strip(): GitHub secrets are easy to save with a stray trailing newline,
# which psycopg happily turns into dbname="postgres\n".
if DB_ENV == "staging":
    DATABASE_URL = os.environ.get("DATABASE_URL_STAGING", "").strip()
else:
    DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()

# Target: early-career software engineering roles (intern / junior / graduate)
# across Europe's tech hubs + remote. Tune from digest logs (plan Phase 6).
PROFILE = {
    # Substring-matched against the title.
    "titles": [
        "software engineer",
        "software developer",
        "software engineering intern",
        "junior software engineer",
        "junior developer",
        "graduate software engineer",
        "new grad software engineer",
        "entry level software engineer",
        "associate software engineer",
    ],
    # At least one of these must appear in the title (career-level gate).
    "levels": [
        "intern", "internship", "junior", "graduate", "new grad", "new-grad",
        "entry level", "entry-level", "associate", "trainee", "apprentice",
    ],
    # Title-scoped: seniority markers plus non-SWE role families
    # (hybrids like "Software Engineer - Frontend").
    "excluded_title_keywords": [
        "senior", "sr.", "staff", "principal", "lead", "manager", "director",
        "head of", "vp", "vice president", "architect",
        "frontend", "front-end", "mobile", "android", "ios",
        "data scientist", "machine learning", "security",
        "sales engineer", "solutions", "recruiter",
        "site reliability", "devops", "qa", "test engineer",
        "embedded", "hardware",
    ],
    "locations": [
        "remote", "europe",
        "berlin", "amsterdam", "london", "paris", "barcelona", "stockholm",
        "dublin", "lisbon", "warsaw", "prague", "vienna", "zurich", "munich",
        "brussels", "milan", "bucharest", "budapest",
        "germany", "netherlands",
    ],
    # Countries whose requirements count as compatible with the user.
    # A posting restricting eligibility to anything else is rejected.
    "eligible_regions": [
        "europe", "european union", "eu",
        "germany", "berlin", "munich", "netherlands", "amsterdam",
        "united kingdom", "uk", "england", "london",
        "switzerland", "zurich",
        "france", "paris", "spain", "barcelona", "sweden", "stockholm",
        "ireland", "dublin", "portugal", "lisbon", "poland", "warsaw",
        "czech republic", "czechia", "prague", "austria", "vienna",
        "belgium", "brussels", "italy", "milan", "romania", "bucharest",
        "hungary", "budapest",
    ],
}
