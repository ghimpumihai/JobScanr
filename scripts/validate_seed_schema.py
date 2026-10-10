"""Fast offline schema validator for seed/companies.json.

Ensures that:
1. File is valid JSON and contains a list of objects.
2. Required fields are present: company_name, career_url, ats_platform, ats_identifier.
3. ats_platform is one of the supported scrapers in scrapers.CLIENTS.
4. career_url is a well-formed http/https URL.
5. Workday identifiers contain exactly 3 segments (tenant|wdN|site).
6. No duplicate (ats_platform, ats_identifier) tuples exist.

Usage:
  python -m scripts.validate_seed_schema
  python -m scripts.validate_seed_schema --file path/to/companies.json
"""

import argparse
import json
import sys
from pathlib import Path

DEFAULT_SEED_FILE = Path(__file__).parent.parent / "seed" / "companies.json"

VALID_PLATFORMS = {
    "greenhouse",
    "ashby",
    "lever",
    "workday",
    "smartrecruiters",
    "teamtailor",
    "google",
}


def validate_companies(data: list) -> list[str]:
    """Validate company list and return a list of error messages."""
    errors = []
    if not isinstance(data, list):
        return ["Seed root must be a JSON array of objects."]

    if not data:
        return ["Seed file contains an empty list."]

    seen_keys = set()
    for idx, c in enumerate(data):
        prefix = f"Entry {idx}"
        if not isinstance(c, dict):
            errors.append(f"{prefix}: expected object, got {type(c).__name__}")
            continue

        name = c.get("company_name")
        url = c.get("career_url")
        platform = c.get("ats_platform")
        ident = c.get("ats_identifier")

        if not name or not isinstance(name, str) or not name.strip():
            errors.append(f"{prefix}: missing or empty 'company_name'")
        else:
            prefix = f"Entry {idx} ({name.strip()})"

        if not url or not isinstance(url, str) or not (url.startswith("http://") or url.startswith("https://")):
            errors.append(f"{prefix}: invalid or missing 'career_url' ({url})")

        if not platform or platform not in VALID_PLATFORMS:
            errors.append(f"{prefix}: unsupported 'ats_platform' '{platform}' (valid: {sorted(VALID_PLATFORMS)})")

        if not ident or not isinstance(ident, str) or not ident.strip():
            errors.append(f"{prefix}: missing or empty 'ats_identifier'")
        elif platform == "workday":
            parts = ident.split("|")
            if len(parts) != 3 or not parts[0] or not parts[1] or not parts[2]:
                errors.append(f"{prefix}: invalid Workday identifier '{ident}' (must be tenant|wdN|site)")

        key = (platform, ident)
        if key in seen_keys:
            errors.append(f"{prefix}: duplicate platform/identifier tuple {key}")
        seen_keys.add(key)

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate seed/companies.json schema.")
    parser.add_argument("--file", type=Path, default=DEFAULT_SEED_FILE, help="Path to seed companies JSON file")
    args = parser.parse_args()

    if not args.file.exists():
        print(f"ERROR: Seed file not found at {args.file}", file=sys.stderr)
        return 1

    try:
        data = json.loads(args.file.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"ERROR: Failed to parse JSON in {args.file}: {exc}", file=sys.stderr)
        return 1

    errors = validate_companies(data)
    if errors:
        print(f"FAIL: Found {len(errors)} validation error(s) in {args.file}:", file=sys.stderr)
        for err in errors[:20]:
            print(f"  - {err}", file=sys.stderr)
        if len(errors) > 20:
            print(f"  ... and {len(errors) - 20} more errors", file=sys.stderr)
        return 1

    print(f"OK: {args.file} validated successfully ({len(data)} companies).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
