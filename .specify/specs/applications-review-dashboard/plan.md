# Technical Implementation Plan: Applications Tracker

**Feature Slug**: `applications-review-dashboard`  
**Issue Reference**: #48  
**Spec Reference**: [.specify/specs/applications-review-dashboard/spec.md](./spec.md)  
**Status**: Approved (2026-11-23)  
**Replaces**: the plan approved on 2026-11-22 for automatic submission, withdrawn after Task 0.2 (findings kept in the appendix)  

---

## 1. Architectural Strategy & Design Trade-offs

Users change an application's status with an ordinary update through their own Supabase session. The existing `applications_update_own` policy limits them to their own rows. A rewritten trigger allows only the spec's status changes and writes the event. The pipeline stages everything as `manual_apply` and closes rows whose posting has gone.

**One pull request**, from the current branch. No new dependency, service, route or service-role key. The worker and submitters stay unused (D4).

| Choice | Chosen | Rejected because |
|---|---|---|
| How users change status | `update().eq('id').eq('status', from)` under the existing policy; the trigger checks the change | `SECURITY DEFINER` functions need their own ownership checks and grants, and the existing trigger's `auth.role()` test would block them |
| "No other column" rule | Compare `to_jsonb(NEW)` with `to_jsonb(OLD)`, minus `status` and `applied_at` | Listing columns: each new column stays writable until someone adds it |
| Time applied | New `applications.applied_at`, set only by the trigger | Reading `application_events`: filtering and sorting by date would need a join PostgREST cannot filter on |
| Event for a user's change | `AFTER UPDATE` trigger, `SECURITY DEFINER`, only for signed-in users | An insert policy on `application_events` would let users write any event; backend changes already write their own |
| Concurrent tabs | The `status = from` filter: 0 rows changed means "already changed" | A row lock taken from the web |
| Closing | One SQL statement per pipeline run | Showing "closed" from `last_seen_at`: PostgREST cannot filter a tab on a joined date |
| Refusing `auto_submit` | One check in the existing `users` trigger; existing `auto_submit` rows reset by the schema | Replacing the generated `CHECK` constraint on `users` |
| Undo | The same action, with the reverse change | Confirmation prompts: undo is cheaper and covers mistakes |

---

## 2. Component Boundaries & Critical Files

| File | Change |
|---|---|
| `db/schema.sql` | `applied_at`; `dismissed` in the status check; status conversion; `auto_submit` reset; rewritten `protect_application_queue_fields`; new event trigger; `users` trigger: remove the confirmation reset, refuse `auto_submit` (3.1) |
| `db/queries.py` | New `close_unlisted_applications(days=30)`; digest confirmation text |
| `jobs/scrape_and_notify.py` | Stage `manual_apply` on every platform; call `close_unlisted_applications` after `delete_stale_jobs` (not in dry run) |
| `models.py` | `Application.applied_at` |
| `web/src/lib/types/index.ts` | `ApplicationStatus` adds `dismissed`. `ApplicationRecord` loses the invented and worker fields (`screening_question`, `drafted_answer`, `work_authorization`, `scheduled_at`, `attempt_token`, `attempts`, `resume_snapshot`, `submitted_payload`, `submitted_at`) and gains `url`, `added_at`, `applied_at`, `last_seen_at` |
| `web/src/routes/(app)/applications/+page.server.ts` | `load` (tabs, filters, counts, page, profile summary, demo rows); action `setStatus`. Replaces the 501 stub |
| `web/src/routes/(app)/applications/+page.svelte` | Tabs, filters, table, mobile rows, paging, messages with Undo |
| `web/src/lib/components/ApplyDrawer.svelte` (new) | Replaces `ReviewDrawer.svelte` (deleted); keeps its focus trap and Escape handling |
| `web/src/routes/(app)/matches/+page.svelte`, `+page.server.ts` | "Apply" link for every platform; remove "Queue all", the toast handlers and the two 501 actions |
| `web/src/routes/(app)/settings/+page.svelte`, `+page.server.ts` | Remove Card 4 (Review & Confirm) and `confirmCv`, the automatic option, the daily limit, the confirmation badge, the CV help text about automatic submission, and `uploadCv`'s "Automatic submission is off" message. Modes become "Active" and "Paused". `saveAutoApply` accepts only those two and no longer writes the cap |
| `web/tests/settings-actions.test.mjs` | Remove the confirm and auto-submit tests; update the trigger copy in the fake |
| `web/tests/applications-actions.test.mjs` (new) | Real `load` and `setStatus` against a fake, like the settings tests |
| `tests/test_schema_security.py`, `tests/test_queries_multiuser.py` | Static checks (section 4). Remove `test_queue_status_protection_trigger_logic` (a Python copy of the old trigger) and the old trigger text checks |
| `tests/test_pipeline_multiuser.py` | Staging statuses; closing is called, and not in dry run; digest text |
| `tests/test_web_scaffold.py` | Banned strings in `web/src`; no `Queue` in Matches. `test_settings_actions_keep_cv_and_screening_guards` loses its `confirmCv` line |
| `.specify/constitution.md` | 1.5: every platform is manual; no submission without an employer key. **Ask first** |
| `docs/ats_submission_spike.md` | Greenhouse and Lever need an employer key (appendix) |

Run `graphify update .` at the end.

---

## 3. Data Flow & Interfaces

### 3.1 Database

```sql
ALTER TABLE applications ADD COLUMN IF NOT EXISTS applied_at TIMESTAMPTZ;

-- The inline CHECK is named applications_status_check by PostgreSQL. Keep the worker's statuses (D4).
ALTER TABLE applications DROP CONSTRAINT IF EXISTS applications_status_check;
ALTER TABLE applications ADD CONSTRAINT applications_status_check CHECK (status IN
    ('queued', 'pending_approval', 'submitting', 'submitted', 'needs_review', 'failed', 'manual_apply',
     'stale_closed', 'dismissed'));
-- The same list goes into the CREATE TABLE text, for new databases.

-- No submission is possible (Task 0.2). Idempotent; production had no rows on 2026-11-22.
WITH moved AS (
    UPDATE applications SET status = 'manual_apply'
    WHERE status IN ('queued', 'pending_approval', 'needs_review', 'failed', 'submitting')
    RETURNING id
)
INSERT INTO application_events (application_id, from_status, to_status, reason)
SELECT id, NULL, 'manual_apply', 'manual_only' FROM moved;

UPDATE users SET auto_apply_mode = 'approval_required' WHERE auto_apply_mode = 'auto_submit';
```

**`protect_application_queue_fields` (rewritten; same name, trigger and `BEFORE UPDATE`).** For a signed-in caller, using the existing `current_user` / `auth.role()` test:

```sql
IF (to_jsonb(NEW) - 'status' - 'applied_at') IS DISTINCT FROM (to_jsonb(OLD) - 'status' - 'applied_at') THEN
    RAISE EXCEPTION 'Only the application status can be changed';
END IF;
IF (OLD.status, NEW.status) IN (('manual_apply', 'submitted'), ('stale_closed', 'submitted')) THEN
    NEW.applied_at := NOW();
ELSIF (OLD.status, NEW.status) IN (('manual_apply', 'dismissed'), ('stale_closed', 'dismissed'), ('dismissed', 'manual_apply'))
   OR (OLD.status = 'submitted' AND NEW.status = 'manual_apply' AND OLD.applied_at IS NOT NULL) THEN
    NEW.applied_at := NULL;
ELSE
    RAISE EXCEPTION 'This status change is not allowed';
END IF;
```

- An unchanged status falls through to the error, so `applied_at` cannot be set alone.
- `OLD.applied_at IS NOT NULL` limits undo to rows the user marked: the worker never sets it.
- Backend writes are not signed-in and pass unchanged.

**`log_user_application_change()`** is a new `AFTER UPDATE ON applications` row trigger: `SECURITY DEFINER`, `SET search_path = ''`. For a signed-in caller whose status changed, it inserts `(id, OLD.status, NEW.status, 'changed_by_user')` into `public.application_events`. `REVOKE EXECUTE ... FROM PUBLIC, anon, authenticated`: triggers do not need the grant, and nobody may call it directly.

**`protect_user_worker_fields`:** the CV path check and the cap check stay. Remove the block that clears `resume_confirmed_at` and demotes `auto_submit`. Replace the confirmation check with:

```sql
IF NEW.auto_apply_mode = 'auto_submit' THEN
    RAISE EXCEPTION 'Automatic submission is not available';
END IF;
```

The `resume_confirmed_at` column stays, because the unused worker's claim query reads it.

### 3.2 Pipeline

```python
def close_unlisted_applications(days: int = 30) -> int:
    """Close To Apply rows whose posting the scanner has not seen for `days`; one event each."""
```

```sql
WITH closed AS (
    UPDATE applications a SET status = 'stale_closed'
    FROM job_postings jp
    WHERE jp.id = a.job_posting_id AND a.status = 'manual_apply'
      AND jp.last_seen_at < NOW() - make_interval(days => %s)
    RETURNING a.id
)
INSERT INTO application_events (application_id, from_status, to_status, reason)
SELECT id, 'manual_apply', 'stale_closed', 'posting_unlisted' FROM closed
```

- It runs in both workflows (digest daily; Workday every 6 h), right after `delete_stale_jobs(days=30)`, which uses the same age.
- Staging becomes `{"job_posting_id": jid, "status": "manual_apply"}` for every match. The platform branch goes. `ON CONFLICT DO NOTHING` already leaves existing rows alone.
- Digest: `payload.get("confirmation_id") or "marked as applied by you"`. Since the conversion, every `submitted` row comes from the user.

### 3.3 Web

**Load**

| Part | Rule |
|---|---|
| Parameters | `tab` (`to_apply`, `applied`, `not_interested`, `closed`), `platform` (one of seven), `company` (at most 100 characters; `\ % _` escaped, `*` removed, since PostgREST reads it as a wildcard), `from` and `to` (`YYYY-MM-DD` UTC days, `to` inclusive), `page` (integer ≥ 1). Invalid values are ignored |
| Query | `applications` with `job_postings!inner(title, location, url, last_seen_at, companies!inner(name, ats_platform))`; filters on joined columns; order `created_at`, then `id`, descending; `range()` of 50 |
| Date filter | `applied_at` on Applied; `created_at` elsewhere |
| Counts | One exact head count per tab, with the filters |
| Profile summary | One `users` read: name, email, phone, location, three links, CV filename. A missing row is a load error, not demo data |
| URLs | Posting URL through `safeHttpUrl` |

**`setStatus` action.** Form fields: `id`, `from`, `to`.

- Check the pair against the spec's table (the same pairs as the trigger) before any request. A bad pair gets 400.
- Run `update({ status: to }).eq('id', id).eq('status', from).select('id')`.
- 0 rows: 409 "already changed". P0001: 400 with the message. No error code: 503 "outcome unknown", and the row is reloaded. Otherwise 500.
- Success returns the message plus `{ id, from: to, to: from }` for Undo.
- Demo sessions get the existing "nothing is stored" result.

**Page**
- Uses `use:enhance` with the Settings callback pattern: on `error` it shows a message and does not call `update()`.
- One `aria-live` region holds the message and Undo.
- Tabs and filters are links and a `GET` form, so they work without JavaScript.
- `ApplyDrawer` shows the posting link (or a notice), copy buttons (`navigator.clipboard`; on failure the value stays visible and selectable), and a `POST` to `/settings?/downloadCv`, the existing action that redirects to a 60-second link. With no stored CV it links to `/settings`.
- Employer text is shown as text; no `{@html}`.

---

## 4. Testing & Verification Strategy

**Automated (mocks only; each new test must fail with its change reverted)**

| Area | Cases | AC |
|---|---|---|
| Pipeline | Greenhouse, Lever and Workday matches staged `manual_apply`; Paused users none; closing called after cleanup, not in dry run | 1, 3 |
| Queries | Closing SQL: `manual_apply` only, the age parameter, one event per row; digest text | 3, 11 |
| Schema (static) | `dismissed` in both lists; conversion statement; `to_jsonb` comparison; each allowed pair; `applied_at` set by the trigger; event trigger is `AFTER`, definer, empty `search_path`, execute revoked; `auto_submit` refused; confirmation reset removed | 2, 4, 5, 10 |
| Web actions | Each allowed change and its undo; a bad pair; 0 rows; P0001; lost connection; demo | 4, 13 |
| Web load | Each tab; each filter; escaping; date bounds; page 2; unsafe URL; profile missing; no demo rows for real users | 7, 8, 9 |
| Settings | Only two modes accepted; no cap written; `confirmCv` gone | 10 |
| Scaffold | Banned strings in `web/src` ("Queue", "dispatch", "Approve & Submit", "Acme Cloud", "Verified against", "Automatic submission", "Submission confirmed", "worker pool", "Confirm CV"); Matches has an Apply link for every platform | 11, 12 |

Static checks prove the text is present, not that PostgreSQL accepts it.

**Staging (writes; ask before running).** Two test users; remove their rows afterwards.

| Case | AC |
|---|---|
| `apply_schema --staging` twice; old statuses converted, events written once | 2 |
| Each allowed change and undo through the page; events | 4 |
| `PATCH` with the anon key: a disallowed pair; another column (`job_posting_id`, `applied_at`, `user_id`); another user's row; no session | 5 |
| Two simultaneous changes of one row | 6 |
| Filters across joined tables through PostgREST; more than 50 rows | 7 |
| `PATCH auto_apply_mode=auto_submit` | 10 |
| Closing: set one test posting's `last_seen_at` back 31 days and one 29 days, run `close_unlisted_applications`, roll back | 3 |

**Manual:** AC-8, 9, 11, 12, 14 in the browser (keyboard only, phone width, network off during a change).

**Commands (AC-15):**

```bash
ruff check .
ruff format --check .
python -m mypy models.py config.py scrapers/   # .venv/bin/mypy has a stale interpreter path
python -m scripts.validate_seed_schema
python -m pytest tests/
cd web && npm run check && npm test && npm run build
```

---

## 5. Risk Assessment & Safety Circuit Breakers

| Risk | Safeguard |
|---|---|
| A user rewrites another column alongside a status change | The `to_jsonb` comparison covers every column, including future ones; staging proves it |
| The generated constraint name differs from `applications_status_check` | `DROP ... IF EXISTS` would then leave the old check in place and adding `dismissed` would fail loudly. Check the name on staging first (`pg_constraint`) |
| The conversion statement runs on every schema apply | Harmless while nothing creates those statuses. If the worker is ever revived (D4), remove it first. A code comment says so |
| Workday postings go unseen for 30 days while still open (a pod in Cloudflare back-off, or a board skipped repeatedly), and their rows close | Same age at which `delete_stale_jobs` already deletes unreferenced postings. The user can still mark a Closed row Applied |
| `postgres` must bypass RLS for closing and conversion | It already does for every backend write (staging confirms) |
| Merging to `main` applies the schema to production (`sync-db`) | Staging first. Production has no applications, and the only `users` change is the `auto_submit` reset. **Ask first** |
| This partly undoes #47's Settings | Approved as D2. The CV upload and download stay |
| Rollback | Reverting restores the old trigger bodies on the next schema run. Users can then no longer change status, and the extra constraint value and `applied_at` stay, unused. Converted rows stay `manual_apply` |
| Many count queries per page load | Four head counts and one page; no polling |

**Not verified:** none of the SQL has run (no PostgreSQL here); PostgREST filters across two joined tables; the generated constraint name. All three are checked on staging before merge.

**Constitution check:** 1.1 no request while a connection is held. 1.2 the CV download reuses the signed link. 1.3 no descriptions. 1.4 untouched. 1.5 to be rewritten (ask first).

---

## Appendix: Task 0.2 Findings (2026-11-23)

Read-only GET requests; nothing submitted. Sample: 24 postings from 8 Greenhouse boards and 15 postings from 8 Lever sites, chosen at random from `seed/companies.json`, plus each vendor's API documentation.

1. **Both vendors require the employer's API key to submit.**
   - Greenhouse: "This method requires HTTP Basic Auth over SSL/TLS: the Basic Auth username is your API key." Only the submission endpoint needs it; reading postings does not.
   - Lever: `POST /v0/postings/SITE/POSTING-ID?key=APIKEY`, a key "a Super Admin of your account can generate".
   - Neither submitter sends a key. `docs/ats_submission_spike.md` lists both as "None (Public Board)", which is wrong.
   - Expected result: every submission is refused, retried as `server_error`, then marked `failed`. Inferred from the docs; not tested, because testing would mean POSTing to an employer.
2. **Lever's public postings carry no questions.** No `cards` or `customQuestions` in any of the 15 postings, so `LeverSubmitter.fetch_questions` always returns `[]` and maps every posting as `ready`.
3. **Greenhouse CV question:** labelled "Resume/CV" in all 24 postings, required in 19. Its fields are `resume` (`input_file`) and `resume_text` (`textarea`).
4. **Greenhouse cover letter:** optional in every sample; fields `cover_letter` and `cover_letter_text`.
5. **Greenhouse multi-select:** field name is already `question_<id>[]`; options have `label` and `value`.
6. **Greenhouse location:** 6 of 8 boards have required `location_questions`: `location` (text) plus hidden `latitude` and `longitude`. The parser never reads this section. Greenhouse also states it "will not reject applications that are missing required fields".
7. **Other Greenhouse sections:** `compliance` (EEOC) had only optional questions. `data_compliance` (GDPR) had every consent flag `false` in the sample.
