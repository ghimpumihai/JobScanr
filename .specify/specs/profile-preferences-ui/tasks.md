# Implementation Tasks: CV Upload, Candidate Details & Auto-Apply Controls

**Feature Slug**: `profile-preferences-ui`  
**Plan Reference**: [.specify/specs/profile-preferences-ui/plan.md](./plan.md)  
**Spec Reference**: [.specify/specs/profile-preferences-ui/spec.md](./spec.md)  
**Status**: Completed (2026-11-22)  

Each task adds its own tests. Run `python -m pytest tests/` after Python, SQL or test edits, and `npm run check` in `web/` after web edits.

## Phase 0: Worker Identity Fix (separate PR, merges first)
- [x] Task 0.1 (AC-13): Carry the user's email to the submitters.
  - `db/queries.py`: select `usr.email` as the last column of `claim_next_queued_application`; add `email` to the claim dict with the `auth_user_id` length guard.
  - `jobs/apply/runner.py`: `ApplicationClaim.email: str | None = None`; set it in `run_queue_worker`; add it to `user_dict`.
  - `tests/test_apply_runner.py`: the claim dict carries the email, and the `user` passed to the submitter contains it.
- [x] Task 0.2 (AC-13): Use the name saved by the web form.
  - `jobs/apply/base.py`: `get_candidate_names` falls back to `screening_defaults.full_name` after `resume_data`.
  - `tests/test_apply_submitters.py`: a web-saved name reaches the Greenhouse and Lever payloads; `resume_data` still wins when both exist.
- [x] Task 0.3: Run the Phase 4 checks; open the PR.

## Phase 1: Schema & Data Contracts
- [x] Task 1.1 (AC-10, AC-11, AC-16): `db/schema.sql`: add `resume_confirmed_at`; extend `protect_user_worker_fields` exactly as in plan section 3.1.
  - `tests/test_schema_security.py`: column exists; the confirmation reset comes before the mode check; the 5-25 bound is present.
- [x] Task 1.2 (AC-16): `scripts/migrate_to_multiuser.py`: remove `resume_data` from `DO UPDATE SET`. Assert it in `tests/test_queries_multiuser.py`.
- [x] Task 1.3 (AC-2, AC-17): `web/src/lib/cvFile.ts`: `checkCvFile(name, bytes)` checks size, extension and magic bytes, and returns the content type and a safe display filename (base name, no control characters, 120 characters max).
  - `tests/test_web_scaffold.py`: limits equal `cv_security.MAX_CV_SIZE` and `ALLOWED_EXTENSIONS`; no service-role key under `web/src`.
- [x] Task 1.4: `web/src/lib/types/index.ts`: add phone, location, URLs, sponsorship, years, notice period, `resume_confirmed_at` and the raw upload timestamp to `UserProfile`. Keep `npm run check` green by making new fields optional.

## Phase 2: Server Actions (`settings/+page.server.ts`)
- [x] Task 2.1 (AC-5): Load the new fields; add them to `MOCK_PROFILE`.
- [x] Task 2.2 (AC-5, AC-6, AC-7): Extend `savePreferences` with the fields and limits in plan section 3.2. Merge into stored JSONB; absent leaves a value alone, empty removes contact keys. Refuse a one-word name.
- [x] Task 2.3 (AC-1, AC-3): `uploadCv`, with the cleanup order in plan section 3.3 (unique object name, old object removed last).
- [x] Task 2.4 (AC-1, AC-4): `downloadCv`: 60-second signed URL, 303 redirect.
- [x] Task 2.5 (AC-8): `confirmCv`: required fields, then an update filtered on the displayed upload timestamp; zero rows updated returns 409.
- [x] Task 2.6 (AC-10, AC-12): `saveAutoApply`: enum, integer 5-25, confirmation pre-check.

## Phase 3: Settings Page (`settings/+page.svelte`)
- [x] Task 3.1 (AC-1, AC-9): Move the CV card out of the preferences form into its own multipart form; wire upload (file input with drag and drop) and download; show the real status (no CV / needs confirmation / confirmed). Read `data.profile` reactively, so a new upload can be confirmed without a reload.
- [x] Task 3.2 (AC-5): Add contact and screening inputs to the preferences form.
- [x] Task 3.3 (AC-8, AC-12): Add the saved-details summary, the confirm button and the auto-apply card (mode, cap slider). `auto_submit` is unavailable until confirmed; the paused label and the "already queued applications are still sent" note are visible.
- [x] Task 3.4 (AC-14, AC-15): Remove the false toasts and the "is parsed" text; errors use an `aria-live` region; keyboard pass.
- [x] Task 3.5: `PRODUCT.md`: remove the ReportLab and resume-preview claims.

## Review Fixes (2026-11-22)
- [x] Task R.1 (AC-18): `db/queries.py` claims only for a confirmed CV; assertion in `tests/test_apply_runner.py`.
- [x] Task R.2 (AC-1): download filename encoded once.
- [x] Task R.3 (AC-2, AC-3, AC-17): `web/tests/settings-actions.test.mjs`, `npm test`, `web-test` CI job.

## Phase 4: Verification
- [x] Task 4.1 (AC-17): `ruff check .`, `ruff format --check .`, `mypy models.py config.py scrapers/`, `python -m scripts.validate_seed_schema`, `python -m pytest tests/`.
- [x] Task 4.2 (AC-17): `npm run check`, `npm test` and `npm run build` in `web/` (CI runs only `npm test`).
- [x] Task 4.3: `graphify update .`
- [x] Task 4.4 (**ask first: staging writes**): `python -m scripts.apply_schema --staging` twice, then the manual cases in plan section 4 and every criterion marked "Staging" in the spec. Done 2026-11-22: schema applied twice; trigger checks (AC-10, AC-11), rolled back. Uploads, storage access between users, page saves and the claim query (rolled back) also passed with two staging test users. Not covered: the upload limit on the real host (hosting not chosen).
- [x] Task 4.5 (**ask first: production read**): count `auto_submit` users, who will have to confirm after release. 2026-11-22: the production `users` table is empty, so nobody is affected.

## Release Step (was Task 4.6)
**Ask first: production schema.** Phases 1-3 merge together, only because 4.4 passed; `sync-db` applies the schema to production on merge. Apply the schema before any worker runs this code.

## Follow-ups Outside This Feature
- Edit issue #47 to match spec section 2 (ask first: public).
- Open an issue: new sign-ups get no `users` row.
- #48: move queued rows back when a user leaves `auto_submit`.
