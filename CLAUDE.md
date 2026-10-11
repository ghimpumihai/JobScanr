# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Testing (unit tests skip network and DB integration by default via pytest.ini)
python -m pytest tests/
python -m pytest tests/test_scrapers.py -k "test_ashby"   # single test / filter
python -m pytest tests/ -v --cov=.                        # with coverage

# Linting, formatting & type checking
ruff check .                                              # lint check
ruff check --fix .                                        # autofix lint issues
ruff format --check .                                     # format check (120 char line length)
ruff format .                                             # apply formatting
mypy models.py config.py scrapers/                        # type check core modules (as in CI)

# Validation & maintenance scripts
python -m scripts.apply_schema                            # apply db/schema.sql to production
python -m scripts.apply_schema --staging                  # apply db/schema.sql to staging
python -m scripts.validate_seed_schema                   # validate seed/companies.json
python -m jobs.scrape_and_notify --dry-run               # scrape pipeline without DB writes or email
python -m seed.seed --staging                             # sync companies to staging database
python -m scripts.test_email --limit 5                    # preview email digest rendering
```

## Architectural Gotchas & Guardrails

- **Database Connection Pooler**: Database is Supabase PostgreSQL. Direct host (`db.<ref>.supabase.co`) is IPv6-only; always use the Session Pooler host (`aws-0-*.pooler.supabase.com:5432`) to prevent connection failures in IPv4-only environments.
- **Environment Isolation**: Production uses `.env` (`DATABASE_URL`, `DIGEST_EMAIL`); staging uses `.env.stage` (`DATABASE_URL_STAGING`, `DIGEST_EMAIL_TEST`). Use `--staging` flag or `DB_ENV=staging`.
- **Scraper Concurrency & Rate Limits**:
  - Fast platforms (Greenhouse, Lever, SmartRecruiters, Teamtailor) use a 30-worker semaphore.
  - Workday uses a dedicated 20-worker pool; identifiers must follow `tenant|wdN|site` format.
  - Ashby uses a serialized pacing lock (`asyncio.Lock()` with 0.5s pause) to avoid 429 rate limits and GraphQL drops.
- **Job Description Storage**: Job descriptions are never persisted to PostgreSQL (to save space). They are inspected in-memory during matching. Ashby and SmartRecruiters list endpoints omit descriptions; full descriptions are fetched lazily in `jobs/enrich.py` only for candidates passing title/location pre-filtering.
- **Safety Circuit Breakers**:
  - `scrape_and_notify.py` aborts if company scrape failures exceed 20% (`FAILURE_RATE_LIMIT = 0.2`).
  - `scan_and_fix_links.py` caps pruning defunct companies at 15% (`--max-remove-pct 0.15`).
