# Implementation Tasks: Remote-Browser Apply Spike (F-hybrid)

**Feature Slug**: `remote-browser-apply-spike`  
**Plan Reference**: [.specify/specs/remote-browser-apply-spike/plan.md](./plan.md)  
**Status**: In Progress  

Tasks marked **[LIVE]** send requests to employers' sites or to Browserbase and need the operator's explicit go-ahead
before each run (CLAUDE.local.md). **[DB]** tasks write to staging and need the same go-ahead. Everything else is
offline.

## Phase 0: Preconditions (no code)
- [x] Task 0.1: PR #126 merged to `main`; rebase this branch on it.
- [x] Task 0.2: Add the approved §1.5 amendment to `.specify/constitution.md` (spec §4 wording).
- [x] Task 0.3 (2026-11-24: account on the default free plan; creating a session with `keepAlive` and recording/logging off was accepted, checked with three empty sessions, all released): Create a Browserbase account and project; note whether `recordSession`/`logSession: false` is allowed
      on the plan tier (plan §5). Put `BROWSERBASE_API_KEY`/`BROWSERBASE_PROJECT_ID` in `web/.env` and `.env.stage` only.
- [x] Task 0.4: Read the Browserbase SDK docs for releasing a session and for `timeout`; read how the web app reads the
      user's CV from Supabase Storage today (#123). Record both in plan §2.3 if they differ from it.
- [x] Task 0.5: Confirm the gate thresholds in spec §5.2 (or record the changed ones there).

## Phase 1: Schema & Data Contracts
- [x] Task 1.1: Add `application_fill_plans` and `remote_apply_sessions` to `db/schema.sql` (idempotent), with RLS,
      the partial unique index on open sessions, and the status CHECK (plan §2.1).
- [x] Task 1.2: Extend `tests/test_schema_security.py`: the `authenticated` role cannot write fill plans, reads only
      its own plans and sessions, and cannot open a second `open` session for one application.
- [x] Task 1.3 [DB]: Apply the schema to staging twice (`python -m scripts.apply_schema --staging`); check both runs
      are clean.

## Phase 2: Fill Plan (Python, batch)
- [x] Task 2.1: `jobs/apply/fill_plan.py`: `build_fill_plans(conn, user_ids)` turning `preview_submission` output into
      the plan JSON (plan §3.1); `for_user` holds unmapped and open-ended questions. Add `upsert_fill_plan` and
      `list_fill_plan_candidates` (Greenhouse, `manual_apply`, no plan or plan older than 1 day) to `db/queries.py`.
- [x] Task 2.2: `tests/test_fill_plan.py` with `httpx.MockTransport`: mapped, unmapped, open-ended, closed posting
      (404 → no plan, no error), empty allowlist (no GETs).
- [x] Task 2.3: Call `build_fill_plans` from `jobs/scrape_and_notify.py` after staging, only when
      `REMOTE_APPLY_USER_IDS` is set, skipped on `--dry-run`; questions fetched outside any open transaction. Test that
      the pipeline skips it with no allowlist and on dry run.

## Phase 3: Fill Engine (web, offline)
- [x] Task 3.1: Add `playwright-core` and `@browserbasehq/sdk` to `web/package.json` (exact versions).
- [x] Task 3.2: `web/src/lib/server/remoteApply/fill.ts`: `fillPage(page, plan, profile, cv)` and the standard-field
      label matcher. Never clicks a submit control; skips frames from reCAPTCHA, hCaptcha and Turnstile hosts; returns
      planned/filled/unfilled counts and unfilled labels.
- [x] Task 3.3: `web/src/lib/server/remoteApply/detect.ts`: `captchaVisible(page)` and `isConfirmation(platform, url,
      text)` with placeholder patterns, marked to be replaced in Task 6.3.
- [x] Task 3.4 [LIVE]: Capture rendered DOM snapshots of 5 apply pages per ATS (Greenhouse, Lever, Ashby) into
      `web/tests/fixtures/apply/`, one page at a time, with no form interaction. Strip anything that is not the form.
- [x] Task 3.5: `web/tests/fill-fixtures.test.mjs`: against the snapshots with all network blocked, every planned
      Greenhouse field is located (checks API name vs DOM), standard fields fill on all three ATS, the CV input gets the
      file, and the test fails if any submit control is clicked. Add the Chromium install step to `ci.yml`.

**Phase 3 findings (2026-11-23, 17 saved pages: 7 Greenhouse, 5 Lever, 5 Ashby, read by `web/scripts/capture-apply-fixtures.mjs`):**
- Greenhouse: some boards (Databricks, Datadog) redirect the hosted job page to the employer's careers site, where the
  form is in an iframe. The embed URL `job-boards.greenhouse.io/embed/job_app?for=<board>&token=<job id>` serves the
  form on all 7; fill plans now store it as `posting_url`.
- Lever: every form carries an `h-captcha-response` field, so Lever uses hCaptcha.
- Matcher fixes from the audit of real labels: "First and Last Name" is one field; "ethnicity" contains "city";
  "Legal Name (if different than above)" and "full name of your major" stay empty. Regression test added.
- After the fixes, every standard field and the CV land in the right control on all 17 pages. Greenhouse's location
  field is a combobox whose options load live, so it reports unfilled offline; stage 2 measures it.

## Phase 4: Session Actions (web)
- [x] Task 4.1: `web/src/lib/server/remoteApply/provider.ts`: `createSession` (`keepAlive`, `timeout`, recording off
      where allowed), `liveViewUrl`, `releaseSession`.
- [x] Task 4.2: `remoteStart` in `applications/+page.server.ts`: checks in plan §3.2 order (owner, allowlist,
      `REMOTE_APPLY_ENABLED`, daily cap of 5, status `manual_apply`, no open session, CV present and ≤ `MAX_CV_SIZE`,
      `safeHttpUrl`), then session row, create, fill, disconnect, return the live view URL. Release in `finally` on
      any failure.
- [x] Task 4.3: `remotePoll` and `remoteEnd`: flag off / provider gone / idle 10 min → release and mark; confirmation
      → PR #126's status update then release and `submitted`; `remoteEnd` checks once for confirmation before
      releasing. Never log or store the live view URL.
- [x] Task 4.4: `web/tests/remote-apply-actions.test.mjs` with a fake provider and fake page: every refusal, the
      confirmation path (status update filtered on `manual_apply`), an ambiguous confirmation (no change), provider
      errors (`error` row, release called), two starts for one application (second refused).
- [x] Task 4.5: Kill script (written as `scripts/remote_apply_kill.py`, so it reaches the database directly): lists running sessions in the project and releases
      them; marks open rows `expired`. Unit test with a fake provider.

**Phase 4 notes (2026-11-23):**
- Session logic lives in `web/src/lib/server/remoteApply/session.ts`; the three actions in
  `applications/+page.server.ts` are thin wrappers. Config is read from `process.env`, like the rest of the web app.
- The remote browser only ever opens `job-boards.greenhouse.io`, `jobs.lever.co` or `jobs.ashbyhq.com` over https.
- Idle close is a maximum session age, not 10 minutes idle; simpler and the same cost bound. The app ends sessions
  at 13 minutes and the providers keep them 15 (Browserbase's free-plan cap), so the app's last check can still
  read the confirmation page (changed 2026-11-26 after review).
- `fields_changed_by_user` is not measured: it needs the filled values kept between polls, which the spec forbids
  storing. Stage 2 measures fill accuracy with the fake persona instead.
- Error messages from a CDP connection can contain the connect key, so only the error's name is logged or stored.

## Phase 5: Drawer UI
- [x] Task 5.1: `ApplyDrawer.svelte`: "Fill it for me" for allowlisted users only; consent notice before the first
      start; live view iframe (`sandbox="allow-same-origin allow-scripts"`); the "left for you" field list; poll every
      3 s while open; stop polling on close; fall back to the normal Apply link on any error.
- [x] Task 5.2: Svelte autofixer, `npm run check`, `npm run build`; keyboard and 375 px check in demo mode with a fake
      provider.

**Phase 5 notes (2026-11-24):**
- `RemoteFill.svelte` sits at the top of the drawer for trial users on Greenhouse, Lever and Ashby To Apply rows;
  the consent notice is shown before every session. The drawer widens to 1100 px while the live view is open
  (`has-[iframe]`), and closing the drawer mid-session ends it (`keepalive` request).
- Focus moves to each new step (found in the keyboard check: it fell to the page body once the pressed button
  disappeared). Checked in demo mode at 375 px: keyboard into the drawer, consent, the demo refusal, Try again,
  Escape back to the row; no horizontal scroll.
- Not checked: the live view step itself (needs a real Browserbase session, Task 0.3).
- `startSession` now expires an application's open rows older than 15 minutes first, so a session nobody polled
  (drawer closed while starting) cannot block that application.

## Phase 6: Stage 2, Live Fill-Only Measurement
- [x] Task 6.1 (2026-11-24; postings and Greenhouse plans for the fake person come from `scripts/spike_postings.py`; the local baseline is a visible Chromium window): `web/scripts/fill-spike.mjs` (plan §3.4): fake persona and dummy CV, Browserbase then local headed
      Chromium per posting, one at a time, Ashby paced ≥ 0.5 s, never submits, refuses without `--confirm-live`, writes
      results JSON and screenshots to an uncommitted folder. Unit-test the argument guard and that no submit is called.
- [ ] Task 6.2 [LIVE]: Run on 30 Greenhouse, 15 Lever and 15 Ashby postings. Record fill accuracy, visible-captcha
      rate for both browsers, and time.
- [ ] Task 6.3: Replace the placeholder confirmation patterns in `detect.ts` with ones from public documentation or
      employer-consented submissions (stage 3); never by submitting to a real employer.
- [ ] Task 6.4: **Gate check** against spec §5.2 (fill accuracy, captcha rate and its gap to the baseline). Fail →
      write the report (Task 8.1) and stop.

**Two providers (2026-11-24, at the user's request):** Cloudflare Browser Run was added next to Browserbase.
`REMOTE_APPLY_PROVIDER` picks the provider for new sessions; each session is always checked and closed through the
provider recorded on its row. Cloudflare is reached from outside Workers over CDP with a bearer token
(`Browser Rendering - Edit`): `POST /devtools/browser?keep_alive=` creates a session, `wss://…/devtools/browser/{id}`
reconnects, `Cloudflare.getLiveView` (mode `tab`) gives the live view, `DELETE` closes it, `GET /devtools/session`
lists them; recording is off by default. Its free plan allows 10 minutes a day and one new browser every 20 s, so
the runner spaces Cloudflare sessions and stops using it on a 429; the web app reports a 429 as no free time left.
Stage 2 now runs the same postings in Browserbase, Cloudflare and the local window. Checked live on 2026-11-25 with
one empty session through the app's provider code: create, connect, the session survives a disconnect, the session
list finds it, reconnect, a live view URL on `live.browser.run`, close. Not yet checked: embedding that live view in
the drawer's iframe.

**First live trial (2026-11-25, 3 postings × Browserbase, Cloudflare, local window; nothing submitted):**
- Postings file: 54 postings (30 Greenhouse, 9 Lever, 15 Ashby; only 3 Lever companies had recent postings);
  Greenhouse fill plans for 28 of 30 (2 postings had closed).
- Standard fields and the CV filled in every browser on Lever and Ashby. On the Stripe Greenhouse form, 5–6 fields
  filled, but the screening dropdowns did not.
- Bugs found and fixed: (1) positional lookups moved values into the wrong fields once Greenhouse's dropdowns
  inserted inputs (local run: Phone got the city); controls are now tagged once and found by tag. (2) each dropdown
  with no exact option waited Playwright's 30 s default (Greenhouse fill took ~100 s); every wait is now 2 s, and
  dropdowns are opened by a click and closed with Escape when nothing matches. (3) screenshots were not saved (wrong
  path type). (4) hidden captcha frames could count as shown; only a visible frame over 30 px counts now.
  Regression test added; it fails with the old lookup.
- Captcha flags (before fix 4): Lever and Ashby showed one in both cloud browsers and none locally. To be re-checked
  with screenshots.
- Fill time per form (before the fixes): Lever 3–8 s remote vs 0.2 s local; Ashby 2–4 s remote vs 0.05 s local.
- "Required filled" counts every required control, including employer-specific questions the profile cannot answer
  (Stripe: 33), so the 95% gate needs a narrower definition: required fields JobScanr is meant to fill.

**Trial re-runs (2026-11-25, same 3 postings, after the fixes above):**
- Second run: no captcha in any browser, so the first run's flags were hidden challenge frames. Greenhouse
  dropdowns filled in both cloud browsers (fill 13–22 s, down from ~100 s) but not locally, and Lever cleared
  "Full name" in Browserbase after reading the CV.
- Fixes: attach the CV first and wait for the page to settle, check typed fields once at the end and refill any
  that were cleared, and wait up to 1 s for a dropdown list to open before typing into it. Test added.
- Third run, identical in all three browsers: Greenhouse 8 of 9 (both screening dropdowns, checked in the
  screenshot: eligible "Yes", sponsorship "No"; the city search left for the user), Lever 8 of 8 including the
  name, Ashby 4 of 4. Fill time: Greenhouse 30 s Browserbase / 18 s Cloudflare / 7 s local; Lever 19 / 6 / 6 s;
  Ashby 6 / 5 / 3 s (includes the wait for the CV read). No captcha anywhere. No sessions left running.

## Phase 7: Stages 3 and 4
- [ ] Task 7.1: Arrange consenting targets (a Greenhouse or Lever sandbox, or a cooperating employer); write down who
      agreed and to what.
- [ ] Task 7.2 [LIVE][DB]: ≥ 10 full-flow submissions on those targets through the drawer on staging. Check each is
      recorded once, on the right application, with the values the tester saw.
- [ ] Task 7.3: **Gate check**: zero wrong submissions. Fail → report and stop.
- [ ] Task 7.4 [LIVE][DB]: Pilot on production: ≤ 5 opted-in users, cap 5 per day, 2 weeks, kill script tested once
      at the start. Collect time to submit and the employer-response comparison.
- [ ] Task 7.5: **Gate check**: time to submit and parity (spec §5.2).

## Phase 8: Report & Verification
- [ ] Task 8.1: `docs/remote_browser_apply_spike.md`: per-stage metrics, provider notes, gate results, the go / no-go
      decision and the recommendation between this hybrid and option A.
- [ ] Task 8.2: `ruff check .`, `ruff format --check .`, `mypy models.py config.py scrapers/`.
- [ ] Task 8.3: `python -m pytest tests/`, `cd web && npm test && npm run check && npm run build`.
- [x] Task 8.4: dropped on 2026-11-26: graphify was removed from the project.
