"""Central config: hardcoded user profile + env-driven secrets."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# Tolerate import in contexts that don't touch the DB (tests); the DB layer
# raises a clear error if these are empty when actually connecting.
# strip(): GitHub secrets are easy to save with a stray trailing newline,
# which psycopg happily turns into dbname="postgres\n".
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
# Secondary delivery channel until the mobile app subscribes to FCM's
# job_alerts topic. Set to e.g. https://ntfy.sh/<unguessable-topic-name>.
NTFY_TOPIC_URL = os.environ.get("NTFY_TOPIC_URL") or None

# Target: early-career software engineering roles (intern / new grad / junior)
# in regions the user can legally work. Tune from digest logs (plan Phase 6).
PROFILE = {
    # Substring-matched against the TITLE: role must be a software flavor.
    "titles": [
        "software engineer", "software developer",
        "software engineering", "software development",
        "backend", "python",
    ],
    # At least one of these must appear in the TITLE: the career-level gate.
    "levels": [
        "intern", "internship", "working student", "student",
        "new grad", "new-grad", "graduate", "junior", "associate",
        "entry level", "entry-level", "trainee",
    ],
    # Checked against the title — kills whole role families regardless of
    # description wording (non-SWE flavors).
    "excluded_title_keywords": [
        "frontend", "front-end", "mobile", "android", "ios",
        "data scientist", "machine learning", "security",
        "sales engineer", "solutions", "recruiter",
        "site reliability", "devops", "qa", "test engineer",
        "embedded", "hardware",
    ],
    # Scanned across title + description.
    "excluded_keywords": ["senior", "sr.", "lead", "manager", "principal", "staff"],
    "locations": ["berlin", "amsterdam", "remote", "netherlands", "germany"],
    # Regions whose country-specific requirements count as compatible.
    # A posting restricting to any OTHER country is rejected.
    "eligible_regions": [
        "germany", "netherlands", "berlin", "amsterdam",
        "europe", "european union", "eu",
        "austria", "belgium", "bulgaria", "croatia", "cyprus", "czech republic",
        "czechia", "denmark", "estonia", "finland", "france", "greece",
        "hungary", "ireland", "italy", "latvia", "lithuania", "luxembourg",
        "malta", "poland", "portugal", "romania", "slovakia", "slovenia",
        "spain", "sweden",
    ],
}
