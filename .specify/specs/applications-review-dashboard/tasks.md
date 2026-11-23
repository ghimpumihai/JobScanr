# Implementation Tasks: Applications Tracker

**Feature Slug**: `applications-review-dashboard`  
**Plan Reference**: [.specify/specs/applications-review-dashboard/plan.md](./plan.md)  
**Spec Reference**: [.specify/specs/applications-review-dashboard/spec.md](./spec.md)  
**Status**: In Progress  

Each task adds its own tests and leaves the suite green. Run `.venv/bin/python -m pytest tests/` after Python, SQL or test edits, and `npm run check` and `npm test` in `web/` after web edits. A new test must fail when its change is reverted. Use `.venv/bin/python -m ...` for Python commands; `.venv/bin/mypy` has a stale interpreter path.

## Phase 0: Before Coding
- [x] Task 0.1: Confirm #47 is merged. Create the branch from `main`, and include this spec folder in it. Done 2026-11-23: #47 merged as #123 (`9d8c241`); branch `feat/applications-review-dashboard`; baseline checks pass (449 tests).
- [x] Task 0.2 (**ask first: live read-only requests**): Read a few public Greenhouse and Lever postings. Done 2026-11-23: both vendors require an employer API key to submit, and Lever's public postings carry no questions (plan appendix). The spec was re-scoped to a tracker and re-approved on 2026-11-23.
- [x] Task 0.3 (**ask first: staging read**): Read the name of the status check on `applications` from `pg_constraint` on staging. If it is not `applications_status_check`, update plan section 3.1 before Task 1.1. No writes. Done 2026-11-23 in a read-only session, after confirming the staging URL differs from production: the name is `applications_status_check`, with the eight expected statuses and no other check on the table. Plan 3.1 stands.

## Phase 1: Database (`db/schema.sql`)
- [x] Task 1.1 (AC-2): Add `applied_at`, replace the status check with one that includes `dismissed` (also in the `CREATE TABLE` text), convert the old statuses with their events, and reset `auto_submit` users (plan 3.1). Add a code comment that the conversion must go before the worker is revived.
  - `models.py`: `Application.applied_at`.
  - `tests/test_schema_security.py`: `dismissed` in both lists; the conversion's statuses and event; the `auto_submit` reset.
- [x] Task 1.2 (AC-4, AC-5): Rewrite `protect_application_queue_fields`: the `to_jsonb` comparison, the allowed pairs, `applied_at` set or cleared, everything else refused. Add `log_user_application_change` as an `AFTER UPDATE` trigger, `SECURITY DEFINER`, empty `search_path`, execute revoked.
  - `tests/test_queries_multiuser.py`: remove `test_queue_status_protection_trigger_logic` and the old trigger message check.
  - `tests/test_schema_security.py`: each allowed pair; the comparison excludes only `status` and `applied_at`; undo of Applied needs `OLD.applied_at`; the event trigger's settings.
- [x] Task 1.3 (AC-10): `protect_user_worker_fields`: remove the confirmation reset and demotion; refuse `auto_submit`; keep the CV path and cap checks. Update the existing assertions in `tests/test_schema_security.py`.

Phase 1 done 2026-11-23: 452 Python tests and 19 web tests pass; ruff, format, mypy and seed checks pass. The SQL has not been run on any database (Task 5.2). Until Task 3.1, Settings still offers the automatic mode, which the database now refuses with "Automatic submission is not available".

## Phase 2: Pipeline (`db/queries.py`, `jobs/scrape_and_notify.py`)
- [x] Task 2.1 (AC-3): `close_unlisted_applications(days=30)`. Tests in `tests/test_queries_multiuser.py`: the SQL touches only `manual_apply`, passes the age, writes one event per closed row, and returns the count.
- [x] Task 2.2 (AC-1, AC-3): Stage `manual_apply` for every match; call `close_unlisted_applications` after `delete_stale_jobs`. Tests in `tests/test_pipeline_multiuser.py`: Greenhouse, Lever and Workday matches staged as `manual_apply`; a Paused user gets nothing; closing is called, and is not called in dry run.
- [x] Task 2.3 (AC-11): Digest: "marked as applied by you" instead of `APP-<id>`. Test in `tests/test_pipeline_multiuser.py` or the digest tests.

Phase 2 done 2026-11-23: 456 Python tests (run with a guard that fails any real database connection) and 19 web tests pass; ruff, format, mypy and seed checks pass. `tests/test_workday_schedule.py` also runs the pipeline, so it now mocks `close_unlisted_applications` in four places; unmocked, it would have reached the database in `.env`.

## Phase 3: Web
- [x] Task 3.1 (AC-10, AC-11): Settings: remove Card 4 and `confirmCv`, the automatic option, the daily limit, the confirmation badge, the CV help text and `uploadCv`'s automatic-submission message. Modes "Active" and "Paused"; `saveAutoApply` accepts only those and writes no cap.
  - `web/tests/settings-actions.test.mjs`: remove the confirm and auto-submit tests; add "only two modes, no cap written"; update the trigger copy in the fake.
  - `tests/test_web_scaffold.py`: drop the `confirmCv` line from `test_settings_actions_keep_cv_and_screening_guards`.
- [x] Task 3.2 (AC-12): Matches: an "Apply" link (through the existing `safeHttpUrl` value) for every platform; remove "Queue all", the toast handlers and the two 501 actions. Scaffold test: no `Queue` in Matches, and an Apply link with no platform condition.
- [x] Task 3.3 (AC-4, AC-7, AC-8, AC-9, AC-13): `applications/+page.server.ts`: `load` and `setStatus` (plan 3.3). In `web/src/lib/types/index.ts`, add the new fields and `dismissed` only, so the current page still compiles.
  - New `web/tests/applications-actions.test.mjs`: every tab and filter; escaping; date bounds; page 2; unsafe URL; profile missing; demo rows only for demo users; each allowed change and its undo; a bad pair; 0 rows; P0001; lost connection; demo writes nothing.
- [x] Task 3.4 (AC-4, AC-7, AC-8, AC-9, AC-14): `applications/+page.svelte` (tabs, filters, table, mobile rows, paging, message with Undo) and new `ApplyDrawer.svelte`. Delete `ReviewDrawer.svelte`; remove the old fields from `ApplicationRecord` and the demo rows.
- [x] Task 3.5 (AC-11): Scaffold test: none of plan section 4's banned strings anywhere in `web/src`.

Phase 3 done 2026-11-23: 458 Python tests (with the database guard) and 29 web tests pass; `npm run check` and `npm run build` pass; ruff, format, mypy and seed checks pass. The Svelte autofixer reports no issues on the Matches page, the Applications page and `ApplyDrawer`. The banned-phrase test finds 30 claims on `main` and none here. Matches' Apply links name the role for screen readers. Not yet seen in a browser (Task 5.3).

## Phase 4: Documents
- [x] Task 4.1 (**ask first: constitution**): `.specify/constitution.md` 1.5: every platform is manual; no submission without an employer key. Wording approved and saved 2026-11-23.
- [x] Task 4.2: `docs/ats_submission_spike.md`: Greenhouse and Lever submission needs an employer key; link the plan appendix.

## Phase 5: Verification
- [x] Task 5.1 (AC-15): `ruff check .`, `ruff format --check .`, `python -m mypy models.py config.py scrapers/`, `python -m scripts.validate_seed_schema`, `python -m pytest tests/`, then `npm run check`, `npm test` and `npm run build` in `web/`; `graphify update .`. Done 2026-11-23: ruff, format, mypy and seed pass; `pytest` 458 passed (also with a guard that fails any real database connection); `npm run check`, `npm test` (29) and `npm run build` pass; graph rebuilt (2,002 nodes). `graphify label`, which calls an LLM, was not run.
- [x] Task 5.2 (**ask first: staging writes**; AC-2 to AC-7, AC-10): Apply the schema twice, then run plan section 4's staging cases with two test users. Remove the test rows; roll back the closing check. Done 2026-11-23, after checking the staging URL is not production:
  - AC-2: schema applied twice without error. 36 `pending_approval` rows became `manual_apply` with 36 `manual_only` events, once (permanent, by design); no `auto_submit` users existed. Constraint, `applied_at`, both triggers, definer settings and revoked execute grants confirmed.
  - AC-4, AC-5, AC-10: 21 cases as the `authenticated` role with real JWT claims, each rolled back: the six allowed changes (with `applied_at` and one event each); every other pair, `applied_at` alone, `job_posting_id`, `submitted_payload` and `user_id` refused; another user's row and an anonymous caller change nothing; users cannot insert events; `auto_submit` refused; an ordinary settings save still works; backend changes stay unrestricted.
  - AC-6: two sessions changing one row: the second waited 1.8 s, changed nothing, one event. Row and event restored.
  - AC-7: the real `load` with a service-role client: 12 of 12 match SQL (51 rows over two pages, order, counts, platform and company through both joins, literal `%` and `_`, `*`, one-day range). Read isolation between users is the existing select policy and was not retested.
  - AC-3: real `close_unlisted_applications` in a rolled-back transaction: 31 days closes with one event; 29 days, Applied and Not Interested untouched.
  - Staging afterwards: 51 `manual_apply` rows, only the 36 conversion events, user modes unchanged. All 51 staging postings are over 30 days old, so the next staging pipeline run will close every To Apply row.
- [x] Task 5.3 (AC-8, AC-9, AC-11, AC-12, AC-14): Manual pass in the browser: keyboard only, phone width, network off during a change, every banned claim gone. Done 2026-11-23 in Chromium (Playwright), demo mode, local dev server with no Supabase settings:
  - Keyboard: a row's Apply button is reached by Tab alone; the drawer takes focus, Tab and Shift+Tab stay inside, Escape closes it and focus returns to the Apply button. Every action button names its role.
  - Changes: a demo change reports that nothing is stored; a dropped connection shows the "outcome is unknown" message and the page stays up; copying works and the value stays selectable; Closed rows show when the posting was last seen; Applied rows offer Move to To Apply; filters survive a reload and Clear keeps the tab.
  - Phone width (375 px): no horizontal scroll on Applications, Closed, Matches or Settings; the drawer fills the screen.
  - No banned claim in the rendered text of any page; Matches has one Apply link per role (new tab, named); Settings offers only Active and Paused, with no daily limit.
  - Fixed: the drawer's platform badge was lowercase.
  - Finding, not fixed: until the page's JavaScript has loaded, the Apply, Applied and Not interested buttons do nothing (noticeable in dev mode).
  - Not covered: the Undo button (demo changes return no undo; the server side is unit-tested), real staging data in the browser, dark mode, and a screen reader.
- [ ] Task 5.4 (**ask first: commit, push and PR**): Open the pull request. Its description says merging applies the schema to production, and gives the rollback notes from plan section 5.

**Release (ask first: production schema).** Merge only if 5.2 passed; `sync-db` applies the schema.

## Follow-ups Outside This Feature
- Open an issue: delete or archive the worker and the Greenhouse and Lever submitters (D4).
- Edit issue #48 to match the re-scoped spec (ask first: public).
- Open an issue: new sign-ups get no `users` row (carried over from #47).
