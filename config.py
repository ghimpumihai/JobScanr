"""Central config: hardcoded user profile + env-driven secrets."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent

# If '--staging' flag is passed (or DB_ENV=staging), use staging (.env.stage); otherwise prod (.env)
if "--staging" in sys.argv or os.environ.get("DB_ENV") == "staging":
    DB_ENV = "staging"
    env_file = BASE_DIR / ".env.stage" if (BASE_DIR / ".env.stage").is_file() else BASE_DIR / ".env"
    load_dotenv(env_file, override=True)
    DATABASE_URL = (os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_URL_STAGING") or "").strip()
    DIGEST_EMAIL = (os.environ.get("DIGEST_EMAIL_TEST") or os.environ.get("DIGEST_EMAIL") or "").strip()
else:
    DB_ENV = "production"
    load_dotenv(BASE_DIR / ".env", override=True)
    DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
    DIGEST_EMAIL = os.environ.get("DIGEST_EMAIL", "").strip()

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
    # Ghost listings that advertise future possibilities instead of real
    # jobs. Matched case-insensitively anywhere in the posting text.
    "excluded_description_patterns": [
        r"this (exact )?(role|posting|requisition) may not be",
        r"advertis\w+ (a )?potential",
        r"evergreen requisition",
        r"pipeline requisition",
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
