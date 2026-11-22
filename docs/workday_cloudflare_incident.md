# Workday scraping incident: digest timeouts (Nov 2026)

Summary of the investigation into why the daily `digest` workflow started hitting its 60-minute limit, what was
measured, what was changed, and what is still open. Written 2026-11-18.

## 1. Symptom

The `digest` workflow (`.github/workflows/digest.yml`, cron 06:00 UTC) runs the scrape, enrichment, matching and
email in one step, then a link-repair step. Run durations from the Actions history:

| Date (2026) | Result | Duration |
|---|---|---|
| Nov 12, 13, 15 | success | 14-16 min (scrape about 12.7 min) |
| Nov 14 | failure | 28 min (link-repair step timed out on Workday companies) |
| Nov 16 | cancelled | 60 min (no output after "Scraping 3618 companies...") |
| Nov 17 | cancelled | 60 min (same) |
| Nov 18 | cancelled | scrape step succeeded after 59 min, then the 60-minute job cap killed the link-repair step |

The Nov 18 run's CI log was unavailable (`log not found`), so per-platform timing could not be read from it.

## 2. What was ruled out

- **Runner and dependencies:** the Nov 15 (good) and Nov 16/17 (bad) runs used the same runner image
  (`ubuntu-26.04`, 20261111.196.1), the same Python and identical pinned and transitive dependency versions.
- **Our code:** nothing in the scrapers, config or workflow changed between them. The last change to
  `scrapers/workday.py` and `scrapers/base.py` was in October. The only commit between the last good and first bad
  run was a 4-company seed swap (#99).
- **Not a new problem:** run history shows earlier slow or hung episodes that recovered without code changes
  (Oct 10, Oct 17, Oct 21-28, Oct 29-30, Nov 14).

## 3. Measurements

### 3.1 Local dry runs (Nov 17, with per-platform timing from #100)

- Greenhouse, Lever, Ashby, SmartRecruiters and Teamtailor finished in about 14 minutes combined. Ashby averaged
  0.4 to 0.5 s per company.
- Workday averaged about 41 s per company with 20 workers (1,634 companies, about 62 minutes projected).
- With 40 workers the scrape finished in 33 minutes, but 75% of Workday companies failed with
  `retries exhausted` (1,243 of 3,618 companies failed overall, over the 20% abort limit). More workers did not
  help; they produced more failures.

### 3.2 Probe (15 single requests, 1 per second, the same POST the scraper sends)

- **wd1:** 5 of 5 returned HTTP 429 in about 0.5 s.
- **wd5:** 5 of 5 returned HTTP 429 in about 0.5 s.
- **wd3:** 5 of 5 answered normally.
- The 429 responses carry `cf-mitigated: challenge`, `server: cloudflare` and a ~28 KB Workday-branded HTML
  challenge page. That is a Cloudflare bot-management challenge, not a slow server and not an ordinary rate limit.
- Ashby (3 boards through the real client) was fine, 0.2 to 0.5 s per board.

## 4. Root cause

`BaseClient.request_with_retry` treats every HTTP 429 as a transient rate limit and sleeps
`1 + 3 + 6.75 + 13.5 + 25.3 = 49.6 s` across five attempts per request, then fails the company.

Workday's wd1 and wd5 pods challenge our requests. 73% of the 1,638 Workday seed entries (684 on wd1, 505 on wd5)
sit on those pods, so roughly 1,190 companies x 49.6 s / 20 workers is about 49 minutes of pure sleeping, which
matches the observed 59-minute scrape. It also matches the measured 41-44 s per company and the 75% failure rate
at 40 workers.

### What is not established

- **Why the challenge started or stops.** Either Cloudflare/Workday changed a policy, or our daily traffic from one
  IP affects our reputation. Both fit the on-and-off history. Not proven either way.
- **How strongly CI is challenged.** The Nov 18 run finished with under 20% failures (a step that aborts on a higher
  rate would have failed), so CI was challenged less than my machine, whose IP had also made many test requests.
  Not confirmed from the run itself.

## 5. Changes made

| PR | State | Purpose |
|---|---|---|
| #100 | merged | per-platform `Scrape progress` log lines (finished/total, average seconds, errors) |
| #101 to #105 | merged | unrelated security-audit fixes (see `~/security-audit-skill/JobScanr/run-1/REPORT.md`) |
| #106 | open (symptom fix) | Workday rotation every N days, 40-minute Workday cap, digest job timeout 60 to 90 min |
| #107 | open (root-cause fix) | treat Cloudflare challenges as blocked, not as rate limits (see below) |

### PR #107 in detail

- `BlockedByChallenge` is raised immediately (no sleep, no retry) when a response is 429 with
  `cf-mitigated: challenge`. A plain 429 still backs off as before.
- Per-host circuit breaker in `request_with_retry`: after 5 consecutive challenges with no success, that pod
  (Workday keyed by pod, e.g. `wd1.myworkdayjobs.com`) is skipped for the rest of the run without sending requests.
  It also covers the enrichment phase.
- `scrape_all` reports blocked companies separately. They are not failures, so they cannot trip the 20% breaker and
  abort the whole digest. They are written to `failures.json` flagged `blocked`.
- `scripts/scan_and_fix_links.py` ignores `blocked` entries (they are healthy boards we could not reach, not dead
  links), so it will not recover, rewrite or prune them, and a blocked-only file no longer falls back to the log or
  stdin.
- Trade-off: while Workday challenges us, blocked Workday companies produce no new postings. The digest still goes
  out for everything else; the only signal is a warning line.
- Not exercised against live traffic after the change; covered with mock transports (388 tests passing).

#106 becomes redundant if #107 is merged. It can be closed, or kept only to lower Workday request volume.

## 6. Decisions and boundaries

- **No evasion.** The challenge exists to turn automation away. I did not build, and will not build, a way past it:
  browser impersonation, stealth patches, spoofed fingerprints, residential proxies, or driving Workday with
  Selenium or Playwright for the daily scan. Retrying cannot pass a challenge and only adds load.
- **Selenium/Playwright is appropriate later,** for the Workday auto-apply submitter (one user's application at a
  human pace; Workday forms are a multi-step web app with no API). The challenge may still appear there and would
  need testing first.
- Auto-apply today supports Greenhouse and Lever only (`resolve_submitter` in `jobs/apply/runner.py`); everything
  else, Workday included, goes to `ManualApplySubmitter`. So skipping Workday in the scan loses only "apply
  manually" leads.

## 7. Alternatives for finding Workday jobs without calling Workday

### 7.1 Simplify listings (`europe_listings.json` analysis)

The provided file (1,126 listings, only `name` and `url`) is a Europe-filtered slice of Simplify data.

- 499 listings (44%) are on Workday: 150 tenants, 141 already in the seed (about 10% of the seed's 1,388 unique
  Workday tenants), only 9 new tenants (18 listings).
- 56% of the Workday listings are on wd1/wd5.
- Early-career software-ish titles: 127 by a loose filter, 78 by a stricter one; about 78 and 55 respectively in
  Europe. These are upper bounds, heavily UK-weighted, with some false positives.
- The export dropped the title, date and `active` fields. The raw Simplify files (already read by
  `scripts/harvest_companies.py`) are believed to include `title`, `locations`, `active` and `date_posted`; this was
  not verified. Coverage would stay small either way.
- Conclusion: a small informational lead list, not a replacement for scanning Workday.

### 7.2 DuckDuckGo experiment (12 queries, 12 s apart, nothing sent to Workday)

- `site:myworkdayjobs.com ...` queries returned 7 results each (a hard ceiling from `ddgs`), and 2 of 12 queries
  returned nothing (throttling).
- 51 unique Workday URLs: 30 job pages, 21 search or listing pages; 23 tenants (21 already in the seed).
- Overlap with the Simplify file: only 2 of 30 job IDs, so the sources are complementary.
- 28 of 30 job pages have early-career software-ish titles, but only 5 are clearly European, because 24 of 30 URLs
  carry no location and most hits were US "Summer 2027" internships. A European filter would need the result
  snippet text, which was not saved.
- Limits: no dates or open/closed status, unofficial scraping of DuckDuckGo (can break or be blocked, CI IPs are the
  likeliest to be throttled), and about 2 to 3 new job pages per query.

### 7.3 Proposed combination (not built)

1. `--skip-platforms workday` so the daily scan sends no Workday requests.
2. Search-based discovery: per-tenant queries (`site:{tenant}.wdN.myworkdayjobs.com intern graduate ...`), about 100
   to 150 a day rotating through the 1,388 tenants (roughly 10 to 14 days for a full cycle), plus a few
   keyword-and-country queries, with pacing, throttle handling and stored snippets for location filtering.
3. Optionally the Simplify feed for the roughly 70 European roles it covers.
4. Show results in the digest as informational, manual-apply, "unverified, from search". When Workday auto-apply is
   built, direct scanning replaces them, deduplicated by the Workday job ID (the `_R12345` suffix in the URL).

## 8. Open questions

- Merge #107? Close #106?
- Build the search-based discovery PR (with `--skip-platforms workday`)?
- Should blocked-company counts be surfaced beyond the log warning (digest note or GitHub issue)?
- Why did the challenge start, and is it tied to our traffic volume? Next scheduled runs with #100's logs (and #107
  if merged) will show per-platform timing and the blocked count.
