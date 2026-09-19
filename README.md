<div align="center">

# 🔭 JobScanr

**A personal radar that watches 350+ tech companies across Europe and emails you the moment an internship, junior, or graduate software engineering role appears.**

![python](https://img.shields.io/badge/python-3.12-blue)
![platforms](https://img.shields.io/badge/ATS-Greenhouse%20%C2%B7%20Ashby%20%C2%B7%20Lever%20%C2%B7%20Workday-purple)
![cost](https://img.shields.io/badge/cost-%240%2Fmonth-success)

</div>

---

## What it does

Once a day, a GitHub Actions cron wakes up and:

```
        06:00 UTC
            │
            ▼
┌───────────────────────┐      ┌──────────────────────────┐
│ 1 · SCRAPE            │      │ 2 · ENRICH               │
│ 357 career boards     │ ───► │ listings without         │
│ across 5 ATS platforms│      │ descriptions get fetched │
└───────────────────────┘      │ individually             │
                               └────────────┬─────────────┘
                                            ▼
┌───────────────────────┐      ┌──────────────────────────┐
│ 4 · EMAIL DIGEST      │      │ 3 · FILTER               │
│ HTML table, every row │ ◄─── │ early-career SWE only    │
│ links to the real     │      │ + country-restriction    │
│ application page      │      │ detection + exp. gates   │
└───────────────────────┘      └──────────────────────────┘
```

You get **one email per day, maximum**. No account system, no UI, no server — just a script that runs itself for free.

---

## The filter

Only postings that survive *all* of these reach your inbox:

| Gate | Rule |
|------|------|
| 🎯 **Role family** | title contains *software engineer / developer* flavors |
| 🎓 **Career level** | title carries *intern / internship / junior / graduate / new grad / entry level / associate / trainee / apprentice* |
| 🚫 **Excluded families** | frontend, mobile, security, data science, DevOps, QA… |
| 🚫 **Seniority** | senior, staff, principal, lead, manager, director, head of, VP, architect |
| ⏳ **Experience** | any `5+ years` style requirement anywhere in the posting |
| 🌍 **Geography** | remote/Europe or one of ~19 hub cities |
| 🛂 **Country restrictions** | *"must be based in the United States"* → rejected; *"right to work in the UK"* → fine |

Everything is one editable dict in [`config.py`](config.py). Start noisy, tune from real digests.

## Coverage

| Platform | Companies | Notes |
|----------|----------:|-------|
| Greenhouse | 185 | clean public API |
| Ashby | 108 | unauthenticated GraphQL, reverse-engineered from their SPA bundle |
| Lever | 39 | simplest API of the four |
| Workday | 24 | the CXS API: POST-only, `limit` capped at exactly 20, throttles with silent empty pages |
| Google | 1 | custom HTML scraper |

**~40,000+ live postings scanned per run.** Companies are onboarded probe-first — nothing enters the list until its feed is verified alive. Dead feeds (companies migrate ATS constantly) are dropped or re-discovered automatically.

---

## Setup

**Prerequisites:** Python 3.12, two free [Supabase](https://supabase.com) projects (production + staging), an SMTP account (Gmail App Password works), a GitHub repo.

```bash
git clone https://github.com/ghimpumihai/JobScanr && cd JobScanr
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env          # fill in DATABASE_URL + SMTP values
```

```bash
python -c "import sys; sys.path.insert(0,'.'); from db import queries; queries.apply_schema()"
python -m seed.seed
python -m jobs.scrape_and_notify --dry-run
```

**Deploy:** add `DATABASE_URL`, `SMTP_*`, `DIGEST_EMAIL`, and optional `GROQ_API_KEY` (free, no credit card needed via [console.groq.com/keys](https://console.groq.com/keys) for AI-assisted self-healing link repair) as repository secrets → merge to `main` → the schedule takes over. That's the whole ops story.

### Environment isolation

| | production | staging |
|--|-----------|---------|
| trigger | cron + dispatches from `main` | you, locally |
| CLI flag | *(default)* | `--staging` |
| env file | `.env` | `.env.stage` |
| inbox | `DIGEST_EMAIL` | `DIGEST_EMAIL_TEST` |

Experiments can never pollute production state or spam the real reader.

```bash
# Example staging runs:
python -m seed.seed --staging
python -m jobs.scrape_and_notify --staging --dry-run
python -m scripts.test_email --staging --limit 3
```

---

## Self-Healing ATS Links & Automated Triage

When career URLs break (e.g. companies migrate ATS, rename boards, or shut down):
1. **Deterministic Probing**: Checks redirects, known aliases, and Workday clusters.
2. **AI Discovery & Web Search (`ai_fixer.py`)**: For unrecoverable feeds, searches DuckDuckGo across supported ATS domains (`greenhouse`, `ashby`, `lever`, `workday`, `smartrecruiters`) and uses Groq AI (Llama 3.3 70B / GPT-OSS) to analyze candidate boards.
3. **Live Verification Gate**: Candidate links must pass live ATS API validation (`verify_ats`) before acceptance.
4. **Automated Pruning**: Companies confirmed to have migrated to unsupported platforms (Personio, BambooHR, Teamtailor, etc.) or defunct boards are queued for removal.
5. **Strict PR Isolation**:
   - The fixer commits changes **only to `seed/companies.json`** inside an automated Pull Request (`bot/fix-links-...`).
   - The production database is **never touched** by the bot or PR branches.
   - Once the PR is merged into `main`, GitHub Actions runs `python -m seed.seed` on `main` to update the database and cleanly cascade-delete pruned companies.

---

## The toolbox

```
scripts/
  scan_and_fix_links.py    self-healing repair pipeline (deterministic + AI triage)
  ai_fixer.py              DuckDuckGo web search + Groq LLM discovery & verification
  validate_companies.py    health-check every board (exit 1 if >5% dead)
  discover_workday.py      find Workday coordinates via robots.txt
  expansion_batch.py       probe candidate companies at scale
  discover_ats.py          fingerprint a company's current ATS from its careers page
  probe_candidates.py      recover renamed/migrated boards by alias probing
  test_email.py            read-only digest previews (never mutates the DB)
```

Adding a company: guess its identifiers → probe → verify → seed. Adding a Workday company whose careers URL you know takes one command.

---

## CLI Command & Flag Reference

### `python -m scripts.scan_and_fix_links`
Scans scrape failures, discovers & verifies working ATS replacements, triages unrecoverables with AI, and updates `seed/companies.json`.

| Flag | Default | Description |
|------|---------|-------------|
| `--log-file <path>` | `None` | Path to scrape log output (e.g. `scrape.log`). |
| `--failures-file <path>` | `None` | Path to structured failures JSON (e.g. `failures.json`). |
| `--companies-file <path>` | `seed/companies.json` | Path to company seed JSON file. |
| `--report-file <path>` | `fix_report.md` | Path to write the Markdown triage & repair summary report. |
| `--dry-run` | `False` | Discover, verify, and triage fixes without modifying `seed/companies.json` or database. |
| `--ai` | Auto (`True` if `GROQ_API_KEY` set) | Explicitly enable AI search & triage for unrecoverable links. |
| `--no-ai` | `False` | Disable AI search & triage, only running deterministic heuristics. |
| `--prune` | `True` | Remove companies verified to have no supported ATS from `seed/companies.json`. |
| `--no-prune` | `False` | Keep unsupported/dead companies in `seed/companies.json`. |
| `--max-remove-pct <float>` | `0.15` (15%) | Safety circuit breaker: aborts pruning if removal count exceeds this fraction of total companies. |
| `--sync-db` | `False` | Directly synchronize `seed/companies.json` and delete pruned rows from the database. |

### `python -m jobs.scrape_and_notify`
Daily scraping, profile matching, database persistence, and email digest pipeline.

| Flag | Default | Description |
|------|---------|-------------|
| `--dry-run` | `False` | Fetch and match jobs without writing to database or sending emails. |
| `--staging` | `False` | Run against the staging database and environment (`.env.stage`). |
| `--failures-file <path>` | `None` | Path to write structured failure details JSON for downstream self-healing. |

### `python -m seed.seed`
Seeds `companies` table from `seed/companies.json` and prunes obsolete rows.

| Flag | Default | Description |
|------|---------|-------------|
| `--staging` | `False` | Sync companies to the staging database (`.env.stage`). |

### `python -m scripts.test_email`
Preview digest emails without modifying the database.

| Flag | Default | Description |
|------|---------|-------------|
| `--limit <int>` | `5` | How many recent job postings to include in the preview digest. |
| `--staging` | `False` | Read postings from the staging database (`.env.stage`). |

### `python -m scripts.validate_companies`
Validates that every company in `seed/companies.json` has an active public ATS feed. Exits with code 1 if >5% of feeds fail.

---

## Engineering notes

Things we learned the hard way, now encoded as tests:

- **Ashby soft-throttles** with HTTP 200 + null payloads instead of 429s. Every GraphQL call retries with backoff; Ashby gets its own slow concurrency lane.
- **Workday's `limit` silently caps at 20.** Ask for more and it returns an *empty array* — indistinguishable from end-of-results. Pagination trusts nothing.
- **Links must be deterministic.** Workday's API path returns raw JSON in a browser, and its detail endpoint intermittently blips — so human-facing URLs are constructed from listing data, never from a network response.
- **Filter before persistence.** The database is an archive of matches only (~15 rows/day, not ~20,000), which keeps it tiny and makes dedup semantics obvious.
- **Descriptions are scraped but never stored** — they're consumed in-memory during matching and discarded.

## Not doing (yet)

- Workday tenant auto-discovery at scale · salary columns in digests ·  LLM relevance scoring · a mobile app

---

<div align="center">

Built for exactly one job seeker. If that's you: fork it, edit `config.py`, deploy in an afternoon.

</div>
