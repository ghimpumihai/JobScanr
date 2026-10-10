---
name: test-scraper
description: Safely test and debug ATS scraper integrations in dry-run mode without modifying the database or sending notifications.
---

# Test ATS Scrapers (Dry-Run Mode)

Safely test scraper clients and parsing logic for a specific platform or company without committing changes to PostgreSQL or dispatching emails.

Arguments provided by user: `$ARGUMENTS`

## Guidelines

1. **Safety First**:
   - Always run with `--dry-run` or execute unit test mocks.
   - Never write to database or dispatch SMTP emails during testing.

2. **Run Targeted Unit Tests**:
   If testing a specific scraper (e.g., `ashby`, `greenhouse`, `lever`, `workday`, `smartrecruiters`, `teamtailor`, `google`):
   ```bash
   python -m pytest tests/test_scrapers.py -k "$ARGUMENTS" -v
   ```

3. **Dry-Run Full Pipeline Run**:
   To test real extraction and matching against current configuration without side-effects:
   ```bash
   python -m jobs.scrape_and_notify --dry-run
   ```

4. **Validate Live Endpoints (Optional / Prompt First)**:
   If the user specifically asks to test a live endpoint or company feed:
   - Ask for confirmation before hitting live ATS APIs if testing extensive company batches.
   - For offline feed testing, check `fixtures/` or mock HTTP responses with `respx` / `pytest`.
