"""Load seed/companies.json into the companies table (idempotent).

Usage: python -m seed.seed
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
        from db.queries import get_connection
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT id, ats_platform, ats_identifier FROM companies")
            to_delete = [
                row[0] for row in cur.fetchall()
                if (row[1], row[2]) not in valid_keys
            ]
            if to_delete:
                cur.execute("DELETE FROM companies WHERE id = ANY(%s)", (to_delete,))
                print(f"Pruned {cur.rowcount} obsolete company row(s).")
    except Exception as exc:
        print(f"Skipping obsolete cleanup: {exc}")
    print(queries.counts())
    return 0


if __name__ == "__main__":
    sys.exit(main())
