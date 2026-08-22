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

# Start noisy, tune later from digest logs (plan Phase 6).
PROFILE = {
    "titles": ["backend engineer", "software engineer", "python developer"],
    "required_keywords": ["python"],
    "excluded_keywords": ["senior", "lead", "manager", "principal", "staff"],
    "locations": ["berlin", "amsterdam", "remote", "netherlands", "germany"],
}
