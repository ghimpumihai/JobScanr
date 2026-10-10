---
name: verify
description: Run code verification gates including ruff check, ruff format check, mypy, seed schema validation, and pytest.
---

# Verify Code Quality and Tests

Run the following checks in sequence to verify code changes against repository standards and CI requirements:

1. **Ruff Lint Check**:
   ```bash
   ruff check .
   ```
   If issues are reported, you can inspect or run `ruff check --fix .` if safe.

2. **Ruff Formatting Check**:
   ```bash
   ruff format --check .
   ```
   If formatting issues exist, run `ruff format .`.

3. **Mypy Static Type Checking**:
   ```bash
   mypy models.py config.py scrapers/
   ```
   Ensure no type errors are introduced into core models, configuration, or scrapers.

4. **Seed Catalog Schema Validation**:
   ```bash
   python -m scripts.validate_seed_schema
   ```
   Ensures `seed/companies.json` adheres to syntax, platform enums, Workday identifier formats, and uniqueness rules.

5. **Unit Tests**:
   ```bash
   python -m pytest tests/
   ```
   Executes fast test suite (omitting integration and network tests as configured in `pytest.ini`).

Report results clearly, distinguishing between lint/format issues, typing errors, and test failures.
