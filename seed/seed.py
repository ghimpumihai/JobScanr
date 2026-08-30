"""Load seed/companies.json into the companies table (idempotent).

Usage: python -m seed.seed
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from db import queries

SEED_FILE = Path(__file__).parent / "companies.json"


def main() -> int:
    companies = json.loads(SEED_FILE.read_text())
    written = queries.upsert_companies(companies)
    print(f"Seeded {written} rows.")
    # One-off migration: Black Forest Labs moved from Greenhouse
    # (blackforestlabs) to Ashby (black-forest-labs). The old row would
    # otherwise survive because upsert keys on (ats_platform, ats_identifier)
    # and keep failing with 404. Remove it idempotently.
    try:
        from db.queries import get_connection
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM companies WHERE ats_platform='greenhouse' AND ats_identifier='blackforestlabs'"
            )
            if cur.rowcount:
                print(f"Removed {cur.rowcount} legacy Greenhouse row(s) for Black Forest Labs.")
    except Exception as exc:  # e.g. no DATABASE_URL in local dev
        print(f"Skipping legacy cleanup: {exc}")
    print(queries.counts())
    return 0


if __name__ == "__main__":
    sys.exit(main())
