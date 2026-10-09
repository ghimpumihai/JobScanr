"""Load seed/companies.json into the companies table (idempotent).

Usage:
  python -m seed.seed            # sync production database
  python -m seed.seed --staging  # sync staging database (.env.stage)
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import DB_ENV
from db import queries

SEED_FILE = Path(__file__).parent / "companies.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed companies table from seed/companies.json.")
    parser.add_argument("--staging", action="store_true",
                        help="use staging environment (.env.stage)")
    args = parser.parse_args()

    companies = json.loads(SEED_FILE.read_text())
    written = queries.upsert_companies(companies)
    print(f"Seeded {written} rows (env: {DB_ENV}).")
    # Prune obsolete rows not present in seed/companies.json (e.g. ATS migrations or dropped boards)
    valid_keys = {(c["ats_platform"], c["ats_identifier"]) for c in companies}
    try:
        pruned = queries.prune_obsolete_companies(valid_keys)
        for p in pruned:
            print(f"  Pruning obsolete company from DB: {p['name']} ({p['ats_platform']}/{p['ats_identifier']})")
        if pruned:
            print(f"Pruned {len(pruned)} obsolete company row(s).")
    except Exception as exc:
        print(f"Skipping obsolete cleanup: {exc}")
    print(queries.counts())
    return 0


if __name__ == "__main__":
    sys.exit(main())
