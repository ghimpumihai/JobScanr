"""Central config: user profile configuration + env-driven secrets."""

import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent


def setup_logging(level: int | str = logging.INFO) -> None:
    """Configure standard application logging format."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )


def load_environment(staging: bool | None = None) -> str:
    """Load the appropriate environment configuration without clobbering preset variables."""
    global DB_ENV, DATABASE_URL, DIGEST_EMAIL
    if staging is None:
        is_staging = os.environ.get("DB_ENV") == "staging" or (
            hasattr(sys, "argv") and "--staging" in sys.argv
        )
    else:
        is_staging = staging

    if is_staging:
        DB_ENV = "staging"
        env_file = BASE_DIR / ".env.stage" if (BASE_DIR / ".env.stage").is_file() else BASE_DIR / ".env"
        load_dotenv(env_file, override=False)
        DATABASE_URL = (os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_URL_STAGING") or "").strip()
        DIGEST_EMAIL = (os.environ.get("DIGEST_EMAIL_TEST") or os.environ.get("DIGEST_EMAIL") or "").strip()
    else:
        DB_ENV = "production"
        load_dotenv(BASE_DIR / ".env", override=False)
        DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
        DIGEST_EMAIL = os.environ.get("DIGEST_EMAIL", "").strip()
    return DB_ENV


# Initialize default environment
DB_ENV = "production"
DATABASE_URL = ""
DIGEST_EMAIL = ""
load_environment()

# Built-in fallback profile for early-career software engineering roles
DEFAULT_PROFILE = {
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
    "levels": [
        "intern", "internship", "junior", "graduate", "new grad", "new-grad",
        "entry level", "entry-level", "associate", "trainee", "apprentice",
    ],
    "excluded_title_keywords": [
        "senior", "sr.", "staff", "principal", "lead", "manager", "director",
        "head of", "vp", "vice president", "architect",
        "frontend", "front-end", "mobile", "android", "ios",
        "data scientist", "machine learning", "security",
        "sales engineer", "solutions", "recruiter",
        "site reliability", "devops", "qa", "test engineer",
        "embedded", "hardware",
    ],
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


def load_profile(path: str | Path | None = None) -> dict:
    """Load user search preferences from a JSON file, environment variable, or fallback."""
    global PROFILE
    profile_path = None
    if path:
        profile_path = Path(path)
    elif os.environ.get("PROFILE_PATH"):
        profile_path = Path(os.environ["PROFILE_PATH"])
    elif hasattr(sys, "argv") and "--profile" in sys.argv:
        try:
            idx = sys.argv.index("--profile")
            if idx + 1 < len(sys.argv):
                profile_path = Path(sys.argv[idx + 1])
        except ValueError:
            pass

    if profile_path is None:
        profile_path = BASE_DIR / "profile.json"

    if profile_path.is_file():
        try:
            with open(profile_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    PROFILE = loaded
                    return loaded
        except Exception:
            pass

    PROFILE = dict(DEFAULT_PROFILE)
    return PROFILE


PROFILE = load_profile()
