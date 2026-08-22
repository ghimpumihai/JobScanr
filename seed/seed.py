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
    print(queries.counts())
    return 0


if __name__ == "__main__":
    sys.exit(main())
