"""Apply db/schema.sql to target database (idempotent).

Usage:
  python -m scripts.apply_schema            # apply to production database
  python -m scripts.apply_schema --staging  # apply to staging database (.env.stage)
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from db import queries

logger = logging.getLogger(__name__)


def main() -> int:
    config.setup_logging()
    parser = argparse.ArgumentParser(description="Apply database schema (db/schema.sql).")
    parser.add_argument("--staging", action="store_true", help="use staging environment (.env.stage)")
    args = parser.parse_args()

    config.load_environment(staging=args.staging)
    logger.info("Applying database schema to %s environment...", config.DB_ENV)
    try:
        queries.apply_schema()
        logger.info("Database schema applied successfully.")
    except Exception as exc:
        logger.error("Failed to apply database schema: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
