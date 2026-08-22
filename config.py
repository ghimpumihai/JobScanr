"""Central config: hardcoded user profile + env-driven secrets."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# Tolerate import in contexts that don't touch the DB (tests); the DB layer
# raises a clear error if these are empty when actually connecting.
DATABASE_URL = os.environ.get("DATABASE_URL", "")
FCM_CREDENTIALS_PATH = os.environ.get("FCM_CREDENTIALS_PATH", "fcm-service-account.json")

# Start noisy, tune later from digest logs (plan Phase 6).
PROFILE = {
    "titles": ["backend engineer", "software engineer", "python developer"],
    "required_keywords": ["python"],
    "excluded_keywords": ["senior", "lead", "manager", "principal", "staff"],
    "locations": ["berlin", "amsterdam", "remote", "netherlands", "germany"],
}
