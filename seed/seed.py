"""Load seed/companies.json into the companies table (idempotent).

Usage:
  python -m seed.seed            # sync production database
  python -m seed.seed --staging  # sync staging database (.env.stage)
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DB_ENV, setup_logging
from db import queries

logger = logging.getLogger(__name__)

SEED_FILE = Path(__file__).parent / "companies.json"


def main() -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="Seed companies table from seed/companies.json.")
    parser.add_argument("--staging", action="store_true",
                        help="use staging environment (.env.stage)")
    args = parser.parse_args()

    companies = json.loads(SEED_FILE.read_text())
    written = queries.upsert_companies(companies)
    logger.info("Seeded %d rows (env: %s).", written, DB_ENV)
    # Prune obsolete rows not present in seed/companies.json (e.g. ATS migrations or dropped boards)
    valid_keys = {(c["ats_platform"], c["ats_identifier"]) for c in companies}
    try:
        pruned = queries.prune_obsolete_companies(valid_keys)
        for p in pruned:
            logger.info("Pruning obsolete company from DB: %s (%s/%s)", p['name'], p['ats_platform'], p['ats_identifier'])
        if pruned:
            logger.info("Pruned %d obsolete company row(s).", len(pruned))
    except Exception as exc:
        logger.warning("Skipping obsolete cleanup: %s", exc)
    logger.info("Database counts: %s", queries.counts())
    return 0


if __name__ == "__main__":
    sys.exit(main())
