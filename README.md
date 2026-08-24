<div align="center">

# 🔭 JobScanr

**A personal radar that watches 180+ tech companies across Europe and emails you the moment an internship, junior, or graduate software engineering role appears.**

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
│ 183 career boards     │ ───► │ listings without         │
│ across 4 ATS platforms│      │ descriptions get fetched │
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
| Greenhouse | 88 | clean public API |
| Ashby | 66 | unauthenticated GraphQL, reverse-engineered from their SPA bundle |
| Workday | 16 | the CXS API: POST-only, `limit` capped at exactly 20, throttles with silent empty pages |
| Lever | 13 | simplest API of the four |

**~20,000 live postings scanned per run.** Companies are onboarded probe-first — nothing enters the list until its feed is verified alive. Dead feeds (companies migrate ATS constantly) are dropped or re-discovered automatically.

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

**Deploy:** add `DATABASE_URL`, `SMTP_*`, `DIGEST_EMAIL` as repository secrets → merge to `main` → the schedule takes over. That's the whole ops story.

### Environment isolation

| | production | staging |
|--|-----------|---------|
| trigger | cron + dispatches from `main` | you, locally |
| database | `DATABASE_URL` | `DB_ENV=staging` + `DATABASE_URL_STAGING` |
| inbox | `DIGEST_EMAIL` | `DIGEST_EMAIL_TEST` |

Experiments can never pollute production state or spam the real reader.

---

## The toolbox

```
scripts/
  validate_companies.py    health-check every board (exit 1 if >5% dead)
  discover_workday.py      find Workday coordinates via robots.txt
  expansion_batch.py       probe candidate companies at scale
  discover_ats.py          fingerprint a company's current ATS from its careers page
  probe_candidates.py      recover renamed/migrated boards by alias probing
  test_email.py            read-only digest previews (never mutates the DB)
```

Adding a company: guess its identifiers → probe → verify → seed. Adding a Workday company whose careers URL you know takes one command.

---

## Engineering notes

Things we learned the hard way, now encoded as tests:

- **Ashby soft-throttles** with HTTP 200 + null payloads instead of 429s. Every GraphQL call retries with backoff; Ashby gets its own slow concurrency lane.
- **Workday's `limit` silently caps at 20.** Ask for more and it returns an *empty array* — indistinguishable from end-of-results. Pagination trusts nothing.
- **Links must be deterministic.** Workday's API path returns raw JSON in a browser, and its detail endpoint intermittently blips — so human-facing URLs are constructed from listing data, never from a network response.
- **`intern` ≠ `internal`.** All keyword gates match on word boundaries.
- **Filter before persistence.** The database is an archive of matches only (~15 rows/day, not ~20,000), which keeps it tiny and makes dedup semantics obvious.
- **Descriptions are scraped but never stored** — they're consumed in-memory during matching and discarded.

## Not doing (yet)

- Workday tenant auto-discovery at scale · salary columns in digests · twice-daily runs · LLM relevance scoring · a mobile app (the FCM-shaped hole in `notify.py` history is intentional)

---

<div align="center">

Built for exactly one job seeker. If that's you: fork it, edit `config.py`, deploy in an afternoon.

</div>
