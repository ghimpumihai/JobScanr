# Technical Implementation Plan: Remote-Browser Apply Spike (F-hybrid)

**Feature Slug**: `remote-browser-apply-spike`  
**Spec Reference**: [.specify/specs/remote-browser-apply-spike/spec.md](./spec.md)  
**Status**: Approved (2026-11-23)  
**Depends on**: PR #126 merged (manual-apply tracker, status trigger, `applied_at`), and the §1.5 amendment approved.

---

## 1. Architectural Strategy & Design Trade-offs

### 1.1 Approach
JobScanr has no always-on Python server: the pipeline runs as a scheduled batch (`digest.yml`), and the SvelteKit app
answers requests. The spike fits that shape and does not add a server.

1. **Greenhouse question answers are built in the batch, in Python.** For the users on the spike's list (allowlist),
   after the pipeline stages `manual_apply` rows, it calls the existing `GreenhouseSubmitter.preview_submission`
   (a public GET for `?questions=true`, then `map_screening_question`) and stores the result in a new table
   `application_fill_plans`. No mapping logic is ported to TypeScript.
2. **The browser is driven from short SvelteKit server actions**, with `playwright-core` connected to a Browserbase
   session over CDP. Each action connects, works for a few seconds, and disconnects. The Browserbase session stays
   alive between actions (`keepAlive`), so no request runs for minutes and a serverless host is fine.
   - `start`: checks, creates the session, opens the apply page, fills it, attaches the CV, returns the live view URL.
   - `poll` (every 3 s while the drawer is open): reconnects, reads the page URL, whether a visible captcha frame is
     present, and a count of filled fields; detects the confirmation page; closes the session when done.
   - `end`: the user closes the view; releases the session.
3. **Standard fields are filled by label on every ATS** (name, email, phone, location, LinkedIn, GitHub, portfolio,
   CV) with one small TypeScript matcher. That covers Lever and Ashby, whose public APIs give no question schema.
   Greenhouse custom questions come from the stored fill plan; Lever and Ashby custom questions are left for the user.
4. **Recording Applied reuses PR #126's path**: on confirmation, the `poll` action runs the same user-scoped update
   as the "Mark as Applied" button (`manual_apply` → `submitted`, filtered on the old status), so the status trigger
   and event trigger apply unchanged and no new privilege is needed.

### 1.2 Alternatives considered
| Alternative | Why not |
|---|---|
| Long-running Node or Python driver service | New always-on server to host, secure and pay for; not needed when the provider keeps the session alive. |
| Port `map_screening_question` to TypeScript, build plans on demand | Two copies of the mapping rules that drift apart. Batch plans are at most a day old, which is fine for a spike. |
| Add a `fill_plan` column on `applications` | PR #126's trigger refuses user changes to any column except `status`/`applied_at`; a separate table avoids touching it. |
| Cloudflare Browser Run first | Its structured handoff is newer (2026-07-28) and is used through Workers; Browserbase's REST + CDP + iframe live view fits SvelteKit directly. A second provider is optional in stage 2 behind the same three calls. |
| Global kill switch as a DB flag read on every poll | An env flag plus a kill script that releases every running session through the provider API is enough, and needs no table or policy. |

### 1.3 Minimising new code
- Reuse: `GreenhouseSubmitter`, `map_screening_question`, `download_resume_stream`-equivalent web CV access from #123,
  PR #126's status update and triggers, `safeHttpUrl` for the posting URL, existing scraper pacing for the GETs.
- New dependency: `playwright-core` and `@browserbasehq/sdk` in `web/` (no browsers bundled). Stage 1 CI installs one
  Chromium with `npx playwright install chromium`.
- No new Python dependency.

---

## 2. Component Boundaries & Critical Files

### 2.1 Database (`db/schema.sql`, idempotent)
- `application_fill_plans (application_id BIGINT PK REFERENCES applications ON DELETE CASCADE, plan JSONB NOT NULL, built_at TIMESTAMPTZ DEFAULT NOW())`.
  RLS: select own (join to `applications.user_id`); no insert/update/delete for `authenticated`.
- `remote_apply_sessions (id BIGINT IDENTITY PK, application_id BIGINT REFERENCES applications ON DELETE CASCADE, user_id BIGINT REFERENCES users ON DELETE CASCADE, provider TEXT, provider_session_id TEXT, status TEXT CHECK (status IN ('open','submitted','abandoned','expired','error','posting_gone')), fields_planned INT, fields_filled INT, fields_unfilled INT, fields_changed_by_user INT, captcha_seen BOOLEAN DEFAULT FALSE, error TEXT, started_at TIMESTAMPTZ DEFAULT NOW(), ended_at TIMESTAMPTZ)`.
  - Partial unique index on `(application_id) WHERE status = 'open'` (one open session per application).
  - RLS: select/insert/update own rows. `provider_session_id` is not a secret (the live view URL is never stored).
  - Known limit: a user could edit their own metrics. Acceptable for a ≤ 5-user pilot; noted in the report.

### 2.2 Python (batch)
- `jobs/apply/fill_plan.py` (new, small): `build_fill_plans(users, client=None)`; for each allowlisted user's
  Greenhouse `manual_apply` row with no plan or a plan older than 1 day, run `preview_submission` and upsert.
- `jobs/scrape_and_notify.py`: call it after staging, only when `REMOTE_APPLY_USER_IDS` is set; skipped on `--dry-run`.
- `db/queries.py`: `upsert_fill_plan`, `list_fill_plan_candidates`.

### 2.3 Web (SvelteKit)
- `web/src/lib/server/remoteApply/provider.ts`: `createSession()`, `liveViewUrl(id)`, `releaseSession(id)` for
  Browserbase (`keepAlive`, `timeout`, `recordSession: false`, `logSession: false` where the plan tier allows).
  Checked 2026-11-23 (Task 0.4, `@browserbasehq/sdk` docs): `keepAlive` needs the Hobby plan or above; the session
  timeout is `api_timeout` (60–21600 s) in the Node SDK; release is `sessions.update(id, { status: 'REQUEST_RELEASE' })`;
  the live view is `sessions.debug(id).debuggerFullscreenUrl`. The CV is read as the web app already does:
  `users.resume_storage_path` in the `resumes` bucket through `locals.supabase.storage` (the user's own session).
- `web/src/lib/server/remoteApply/fill.ts`: `fillPage(page, plan, profile, cv)` and the standard-field label matcher;
  returns counts and unfilled labels. Never calls `click` on a submit control; never touches frames from
  `google.com/recaptcha`, `hcaptcha.com` or `challenges.cloudflare.com`.
- `web/src/lib/server/remoteApply/detect.ts`: `isConfirmation(platform, url, text)`, `captchaVisible(page)`.
  Patterns filled in from stage 2 observations.
- `web/src/routes/(app)/applications/+page.server.ts`: actions `remoteStart`, `remotePoll`, `remoteEnd`.
- `web/src/lib/components/ApplyDrawer.svelte`: a "Fill it for me" button (allowlisted users only), the consent notice,
  the live view iframe (`sandbox="allow-same-origin allow-scripts"`), the list of fields left for the user, polling.
- `web/scripts/fill-spike.mjs`: the stage 2 runner (below).
- `scripts/remote_apply_kill.py` or `web/scripts/remote-apply-kill.mjs`: releases every running provider session.

### 2.4 Tests
- `tests/test_fill_plan.py`: plan builder with `httpx.MockTransport` (mapped, unmapped, open-ended, 404 posting,
  allowlist empty, dry-run).
- `tests/test_schema_security.py`: new tables' RLS (extends the existing file).
- `web/tests/remote-apply-actions.test.mjs`: refusals (not owner, not allowlisted, flag off, daily cap, already
  submitted, open session exists), confirmation → status update, provider errors → `error` row.
- `web/tests/fill-fixtures.test.mjs` (stage 1): Playwright against saved DOM snapshots in
  `web/tests/fixtures/apply/{greenhouse,lever,ashby}-*.html`; asserts every planned field is located and filled, the
  CV input receives the file, and no submit control was clicked.

### 2.5 Docs
- `.specify/constitution.md` §1.5 amendment (approved wording from the spec).
- `docs/remote_browser_apply_spike.md`: results report.

---

## 3. Data Flow & Interfaces

### 3.1 Fill plan (`application_fill_plans.plan`)
```json
{
  "version": 1,
  "platform": "greenhouse",
  "posting_url": "https://job-boards.greenhouse.io/acme/jobs/123",
  "fields": [
    {"name": "question_456", "label": "Do you require sponsorship?", "type": "single_select",
     "value": 0, "option_label": "No"}
  ],
  "for_user": [{"name": "question_789", "label": "Why Acme?", "reason": "open_ended"}]
}
```
Profile fields and the CV are not stored in the plan; the web action reads them at fill time (they can change).

### 3.2 Session lifecycle
```
remoteStart ─► checks (owner, allowlist, REMOTE_APPLY_ENABLED, cap, status = manual_apply, no open session)
            ─► insert session row (open) ─► provider.createSession ─► connect, goto, fill, attach CV
            ─► disconnect ─► return {sessionId, liveViewUrl}
remotePoll  ─► flag off / provider gone / idle > 10 min ─► release, status expired|abandoned
            ─► confirmation detected ─► PR #126 status update ─► release, status submitted
            ─► else update counts, captcha_seen ─► return state
remoteEnd   ─► release, status abandoned (unless already final)
```
Every path that ends a session calls `releaseSession` in a `finally`; a failed release is logged and left to the
provider's session timeout.

### 3.3 Errors
- Provider create fails, or a 4xx/5xx from the provider: session `error`, the drawer falls back to the normal Apply link.
- Posting 404 or redirect to a jobs list: `posting_gone`; the application is left for the pipeline's 30-day closing.
- Page shape unknown (no standard fields found): fill nothing, hand over with a message, record `fields_filled = 0`.
- Confirmation ambiguous: no status change; the drawer asks the user to mark it.

### 3.4 Stage 2 runner (`web/scripts/fill-spike.mjs`)
- Input: a list of posting URLs (from the DB, read-only) and a **fake test persona** with a dummy CV. No real user data.
- For each URL, in two browsers (Browserbase, then local headed Chromium on the operator's connection): open, wait,
  fill, record counts, captcha visible yes/no, time, screenshot, close. Never submits.
- Paced: one posting at a time, Ashby postings ≥ 0.5 s apart (as the scraper), at most the stage's sample size.
- Output: a JSON results file plus screenshots in a local folder that is not committed.
- Refuses to run without `--confirm-live`.

---

## 4. Testing & Verification Strategy

- **Python**: `httpx.MockTransport` for the questions GET; the existing no-real-DB guard from #125 stays on.
- **Web**: actions tested with a fake provider and a fake Playwright page object (no network); fixtures test uses
  local files only (`page.route('**', abort)` for anything not `file://`).
- **Edge cases**: posting closed between batch and click; plan older than the posting edit (field missing → unfilled);
  two tabs starting a session (unique index → second refused); confirmation while the flag is off (still recorded,
  the user did submit); user submits then closes before the next poll (`remoteEnd` checks once for confirmation before
  releasing); CV missing or over `MAX_CV_SIZE` (start refused).
- **Commands**:
  ```bash
  ruff check .
  ruff format --check .
  mypy models.py config.py scrapers/
  python -m pytest tests/test_fill_plan.py tests/test_schema_security.py
  cd web && npm test && npm run check && npm run build
  ```

---

## 5. Risk Assessment & Safety Circuit Breakers

| Risk | Safeguard |
|---|---|
| An automated Submit | `fill.ts` never clicks; a fixture test fails if any submit control receives a click; code review checklist item. |
| Captcha interaction or evasion | No captcha frames touched; no stealth, proxies or solvers; plain Browserbase defaults. |
| Fraud flags against users (shared provider IPs) | That is what stage 2 measures; pilot capped at 5 users × 5 per day; global flag and kill script. |
| Live view URL leaked | Returned only to the owning user's request, never stored or logged, session released at the end. |
| Personal data at a third party | Per-session consent; recording and logging off where the plan allows (Browserbase's zero-data-retention settings may need an enterprise plan; verify before stage 4, otherwise pilot users are told it is recorded). |
| Wrong posting or duplicate submission | Session tied to one application and its own URL (`safeHttpUrl`); status filtered on `manual_apply`; one open session per application. |
| Cost runaway | Provider `timeout` on every session, idle close at 10 minutes, daily cap, kill script. |
| Greenhouse API field names differ from the form's DOM | Stage 1 fixtures check it before any live run; unmatched fields are left for the user. |
| DB connection held during browser work | Web actions use PostgREST calls before and after the browser work, never a held connection; the batch builder fetches questions outside any transaction. |
| Live requests during tests | Unit and fixture tests have no network; stage 2 and fixture capture need `--confirm-live` and the operator's go-ahead. |
