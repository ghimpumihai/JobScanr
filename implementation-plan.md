# Job Alert App — Implementation Plan (Tier 1, v2)

> **What changed vs v1**
> - **Daily digest replaces hourly cron** — simpler, quieter, and the only cadence that fits the GitHub Actions budget alongside CI/CD.
> - **Single-user**: `user_profile` table dropped; profile lives in `config.py`.
> - **Runs on GitHub Actions**, not an Oracle VM — zero server maintenance.
> - **Teamtailor client cut** — 0 of the 150 companies in `global_companies_europe_ats_150.json` use it.
> - **Safety fixes**: staleness-based cleanup instead of destructive same-run deletes; pagination + HTML stripping are now client requirements.
> - **Phase 0 added**: validate all 150 company endpoints before building anything.

---

## Overview

A personal job alert tool: once a day it scrapes the career pages of 150 top tech companies hiring in Europe, filters postings against a hardcoded profile, and sends **one push notification digest** of new matches. No accounts, no UI, no server — a Python script on a GitHub Actions schedule, Postgres on Supabase, Firebase Cloud Messaging for delivery.

---

## Key Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Users | Just me | Hardcoded profile, topic-based push, no auth |
| Latency | Daily digest | Job postings live for days; hourly polling buys nothing |
| Delivery | Single FCM topic push per day | One tap to scan, zero noise fatigue |
| Runner | GitHub Actions scheduled workflow | Fits free minutes; no VM to patch; cron-as-code |
| Matching | Loose, tuned later | Collect a week of real match data before tightening |
| Scope gate | Push-only until signal proven | Mobile app deferred until alerts prove useful |

---

## Tier 1 ATS Platforms (actual distribution in the company list)

| Platform | Companies | Share | Client priority |
|----------|----------:|------:|-----------------|
| Greenhouse | 102 | 68% | P0 — build first |
| Ashby | 32 | 21% | P0 — build first |
| Lever | 11 | 7% | P1 |
| Workable | 3 | 2% | P2 — undocumented API; drop companies if it breaks |
| SmartRecruiters | 2 | 1% | P2 |
| ~~Teamtailor~~ | 0 | 0% | Cut from MVP |

Greenhouse + Ashby cover 89% of the list — those two clients alone make the system useful.

> Skip any company using Workday or a custom portal.

---

## Phase 0 — Validate the Company List *(new, do this first)*

The biggest assumption is that all 150 `ats_identifier` values are correct. Validate before building anything:

`scripts/validate_companies.py`
- Fetch each company's ATS endpoint once (HTTP status + JSON shape check only).
- Print a pass/fail matrix grouped by platform.
- **Exit 1 if >5% fail.** Fix or remove dead entries in `companies.json`.

This also empirically confirms every API URL in Phase 4 on day one.

---

## Phase 1 — Company List ✅ (done, pending Phase 0 validation)

`global_companies_europe_ats_150.json`: 150 entries, all fields complete, no duplicates. Seeded into the DB by `seed/seed.py`.

---

## Phase 2 — Database Schema

```sql
CREATE TABLE companies (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    ats_platform    TEXT NOT NULL,
    ats_identifier  TEXT NOT NULL,
    career_url      TEXT,
    UNIQUE (ats_platform, ats_identifier)
);

CREATE TABLE job_postings (
    id              SERIAL PRIMARY KEY,
    external_id     TEXT NOT NULL,
    company_id      INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    location        TEXT,
    department      TEXT,
    url             TEXT,
    description     TEXT,            -- stored stripped of HTML
    first_seen_at   TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at    TIMESTAMPTZ DEFAULT NOW(),
    notified_at     TIMESTAMPTZ,     -- NULL = not yet included in a digest
    UNIQUE (external_id, company_id)
);
```

### Changes vs v1
- **`user_profile` removed** — profile is a dict in `config.py`. Reintroduce when there is a second user.
- **`notified_at` added** — if a digest send fails, the next run retries those jobs instead of losing them forever.
- **Staleness cleanup replaces same-run deletion** (see Phase 5).
- `TIMESTAMPTZ`; unique constraint on companies makes seeding idempotent.

---

## Phase 3 — Project Structure

```
scrapers/
    base.py               # shared interface + httpx client + retry/backoff
    greenhouse.py         # P0
    ashby.py              # P0
    lever.py              # P1
    workable.py           # P2
    smartrecruiters.py    # P2
jobs/
    scrape_and_notify.py  # Actions entry point: one invocation = one full cycle
    match.py              # keyword matching
    digest.py             # assemble digest message text
    notify.py             # FCM send
db/
    queries.py            # all DB operations in one place
scripts/
    validate_companies.py # Phase 0 gate
seed/
    companies.json
    seed.py
config.py                 # PROFILE dict + env-driven secrets
requirements.txt
.github/workflows/digest.yml
```

---

## Phase 4 — ATS Clients

```python
# base.py
class BaseClient:
    async def get_jobs(self, ats_identifier: str) -> list[dict]:
        raise NotImplementedError
```

Every client **must**:

1. **Paginate** — several target companies (Stripe, Databricks…) exceed single-page limits. Follow each API's pagination fields until exhausted. Skipping this silently drops most jobs at big companies.
2. **Strip HTML from descriptions** — Greenhouse's `content=true` returns raw HTML; matching keywords against markup is garbage-in-garbage-out.
3. **Return the normalized shape**: `external_id`, `title`, `location`, `department`, `url`, `description` (plain text).

### Endpoints (empirically confirmed by Phase 0)

```
greenhouse       GET https://boards-api.greenhouse.io/v1/boards/{id}/jobs?content=true
ashby            POST https://api.ashbyhq.com/jobPosting.list
                     body: {"organizationHostedJobsPageName": "{id}"}
lever            GET https://api.lever.co/v0/postings/{id}?mode=json
workable         GET https://www.workable.com/api/accounts/{id}/jobs   (undocumented — P2 risk)
smartrecruiters  GET https://api.smartrecruiters.com/v1/companies/{id}/postings?limit=100&offset=...
```

Shared behavior in `base.py`: per-request timeout, exponential backoff on 429/5xx (max 3 tries), one reused `httpx.AsyncClient`.

---

## Phase 5 — Daily Cycle Flow

```python
# scrape_and_notify.py — one run per day
async def main():
    companies = db.get_all_companies()
    results = await asyncio.gather(              # parallel, isolated failures
        *(fetch_company(c) for c in companies),
        return_exceptions=True,
    )
    if failure_rate(results) > 0.2:
        sys.exit(1)                              # red build = investigate

    new_jobs = db.upsert_jobs(successes(results))
    db.delete_stale_jobs(days=3)

    matches = [j for j in new_jobs if matches_profile(j)]
    if matches:
        send_digest(matches)
        db.mark_notified([j["id"] for j in matches])
```

### Cleanup logic (replaces v1's per-company `NOT IN` delete)

```sql
DELETE FROM job_postings
WHERE last_seen_at < NOW() - INTERVAL '3 days';
```

Why: v1 deleted jobs absent from that run's feed, so a single failed or partially-paginated fetch would have **deleted every known job for a company** (and `NOT IN ()` on an empty set is invalid SQL). A 3-day staleness grace absorbs transient failures and costs nothing at this scale.

Upsert uses `INSERT ... ON CONFLICT ... DO UPDATE SET last_seen_at = NOW() RETURNING (xmax = 0) AS is_new`; collect rows where `is_new`. The Actions workflow sets a `concurrency` group so overlapping scheduled runs queue instead of racing.

---

## Phase 6 — Keyword Matching (start noisy)

```python
# match.py
def matches_profile(job: dict, p: dict) -> bool:
    headline = f"{job['title']} {job['location']}".lower()
    text = f"{headline} {strip_html(job['description'])}"

    if not any(t in headline for t in p["titles"]):
        return False
    if not any(k in text for k in p["required_keywords"]):
        return False
    if any(k in text for k in p["excluded_keywords"]):
        return False
    return True
```

Change vs v1: **location is matched against the `location` field only**, not the whole description (phrases like "remote-first culture" in prose caused false positives). Titles match title+location; required/excluded scan full text.

Profile stays loose to start (`config.py`); every run logs matched titles so the first week of digests can be used to tighten keywords with real data.

---

## Phase 7 — Digest Notification

One message per day to topic `job_alerts`:

```python
# notify.py
def send_digest(jobs: list[dict]):
    top = ", ".join(f"{j['title']} @ {j['company']}" for j in jobs[:3])
    more = f" +{len(jobs)-3} more" if len(jobs) > 3 else ""
    messaging.send(messaging.Message(
        notification=messaging.Notification(
            title=f"{len(jobs)} new matching jobs",
            body=(top + more)[:200],
        ),
        topic="job_alerts",
    ))
```

Test delivery from the Firebase console before writing `notify.py` — that alone validates the push path with zero code. Subscribe your phone to the topic with a tiny debug script or console test device.

---

## Phase 8 — Infrastructure & the Actions Minutes Budget

| Part | Tool | Cost |
|------|------|------|
| Scheduler + compute | GitHub Actions scheduled workflow | Free (budgeted below) |
| Database | Supabase free tier | Free |
| Push | Firebase Cloud Messaging | Free |
| HTTP | Python httpx (async) | Free |

### Minutes math (3000 min/month plan, private repo, Linux ×1)

| Cadence | Est. run time | Runs/mo | Scraper min/mo | Left for CI/CD |
|---------|--------------:|--------:|---------------:|---------------:|
| 1×/day | ~6 min | 30 | ~180 | ~2820 |
| 2×/day | ~6 min | 60 | ~360 | ~2640 |

Verdict: comfortably worth it. Even twice-daily leaves >85% of the budget for CI/CD. Hourly (~7200 min/mo) would blow the budget — the daily digest is what makes Actions viable.

Gotchas: keep the repo **private** (you likely don't want your search profile public, even though public repos get unlimited minutes). GitHub disables scheduled workflows after 60 days of repo inactivity — any commit resets the clock, and CI/CD activity counts.

```yaml
# .github/workflows/digest.yml
name: digest
on:
  schedule:
    - cron: "0 6 * * *"        # 06:00 UTC daily — adjust timezone
  workflow_dispatch:           # manual trigger for testing
concurrency:
  group: digest
jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -r requirements.txt
      - run: python -m jobs.scrape_and_notify
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          FCM_CREDENTIALS: ${{ secrets.FCM_CREDENTIALS }}
```

Secrets live only in Actions/Supabase/Firebase consoles — never in the repo. Supabase's free tier pauses projects after 7 days idle; daily writes prevent that.

---

## Build Order

1. **Phase 0**: run `validate_companies.py`; fix dead identifiers
2. Create Supabase project, run schema, seed companies
3. Build Greenhouse + Ashby clients (89% coverage), test against a few real companies each
4. Add Lever, Workable, SmartRecruiters clients
5. Upsert + staleness cleanup in `db/queries.py`
6. Keyword matcher with match logging
7. Digest assembly + FCM send (console-test the push first)
8. Wire `scrape_and_notify.py`, add Actions workflow + secrets, manual `workflow_dispatch` test
9. Run for one week; tune keywords from logs; only then consider the mobile app

---

## Assumptions to Validate

- [ ] All 150 ATS identifiers are live → Phase 0 script (day one)
- [ ] Public APIs don't rate-limit or require keys → ≤150 polite requests/day makes this unlikely; backoff covers bursts
- [ ] Loose keyword matching produces tolerable noise → measure from week one of digests
- [ ] FCM topic push works with no published app → console test before writing notify code
- [ ] Supabase free tier suffices → ~75k rows worst case; yes

---

## Not Doing (and Why)

- **Mobile app** — validate alert quality first; FCM pushes arrive without one
- **Multi-user / profiles table** — it's a personal tool; schema is trivial to extend later
- **Teamtailor client** — zero companies use it in the current list
- **Workday & custom portals** — no clean API; Tier 2 concern
- **Hourly scraping** — postings live for days; daily digest fits budget and sanity
- **AI relevance scoring** — keywords first; add LLM filtering only if tuning can't get noise down
- **Admin UI** — config.py and SQL suffice for one user
- **Oracle VM** — replaced by Actions; nothing to patch, nothing to keep alive

---

## Open Questions

- Preferred digest time/timezone for the cron? (default 06:00 UTC)
- If Workable's undocumented endpoint breaks, drop its 3 companies or scrape their HTML pages?
- Should the digest include closed-since-yesterday jobs (they'd be deleted by staleness cleanup)? Probably not — confirm after first week.

