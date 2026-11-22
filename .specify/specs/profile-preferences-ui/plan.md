# Technical Implementation Plan: CV Upload, Candidate Details & Auto-Apply Controls

**Feature Slug**: `profile-preferences-ui`  
**Issue Reference**: #47  
**Spec Reference**: [.specify/specs/profile-preferences-ui/spec.md](./spec.md)  
**Status**: Converged (2026-11-22)  

---

## 1. Architectural Strategy & Design Trade-offs

Extend the existing `/settings` page and its form actions. The browser posts forms to SvelteKit, which uses the user's own Supabase session, so RLS applies. No new service, dependency, route, or service-role key in `web/`.

| Choice | Chosen | Rejected because |
|---|---|---|
| Upload path | SvelteKit form action, then `locals.supabase.storage` | Direct browser upload needs public env vars plus a second request to update the row. Trade-off: the action is subject to the host's body limit (section 5) |
| Object name | New `<auth uid>/<uuid>.<ext>` per upload; old object deleted after the row update | Overwriting `resume.<ext>` (the CV spec's name) can replace the bytes, then fail the row update, leaving a *confirmed* CV nobody reviewed. Still one active file per user |
| Confirmation gate | `users.resume_confirmed_at` plus the existing `protect_user_worker_fields` trigger | A UI-only check is bypassable: `users_update_own` lets a user PATCH any column with the public anon key |
| Contact storage | `users.resume_data`, which the submitters already read | `screening_defaults.location` is unsafe. Reproduced: "Do you need relocation support?" is confidently answered "London", because the key `location` is a substring of "relocation" (`base.py`, rule 7) |
| Malware scan | The worker's existing `validate_cv` before every submission; upload checks size, extension and magic bytes | Porting the scanner to TypeScript creates two security rule sets that drift |

---

## 2. Component Boundaries & Critical Files

### Phase 0: backend prerequisite (separate PR, recommended)

Reproduced offline on the current code: with a name saved through the web form, the worker's `user_dict` produces the name `Candidate`, an empty last name and an empty email. Two causes:

1. `claim_next_queued_application` does not select `users.email`, and neither `ApplicationClaim` nor `user_dict` carries it.
2. `web/` saves `screening_defaults.full_name`; `get_candidate_names` reads only `resume_data`.

No workflow or script calls `run_queue_worker`, so nothing scheduled in this repo is submitting these today. It must be fixed before `auto_submit` is selectable.

| File | Change |
|---|---|
| `db/queries.py` | Select `usr.email` as the last claim column; add `email` to the claim dict, using the same length guard as `auth_user_id` |
| `jobs/apply/runner.py` | `ApplicationClaim.email` (default `None`); pass it where `run_queue_worker` builds the claim, and into `user_dict` |
| `jobs/apply/base.py` | `get_candidate_names`: fall back to `screening_defaults.full_name` after `resume_data`. Fixes names already saved |
| `tests/test_apply_runner.py`, `tests/test_apply_submitters.py` | Claim carries email; payload has the real name and email |

### Phases 1-3: feature

| File | Change |
|---|---|
| `db/queries.py` | `claim_next_queued_application` also requires `u.resume_confirmed_at IS NOT NULL` |
| `db/schema.sql` | `resume_confirmed_at` column; extend `protect_user_worker_fields` (section 3.1) |
| `web/src/lib/cvFile.ts` (new) | `checkCvFile(name, bytes)`: size, extension, magic bytes, display filename |
| `web/src/lib/types/index.ts` | New `UserProfile` fields, including the raw `resume_uploaded_at` timestamp (the current one is already formatted for display, so `confirmCv` cannot filter on it) |
| `web/src/routes/(app)/settings/+page.server.ts` | Load new fields; extend `savePreferences`; add `uploadCv`, `downloadCv`, `confirmCv`, `saveAutoApply` |
| `web/src/routes/(app)/settings/+page.svelte` | CV card becomes its own multipart form outside the preferences form (HTML forbids nested forms). The CV, confirmation and auto-apply cards read `data.profile` reactively: the current `const profile = data.profile` is captured once, so after an upload the page would post the old timestamp and every confirmation would return 409. Contact and screening inputs; auto-apply card |
| `tests/test_schema_security.py` | Static checks for the new trigger rules |
| `tests/test_web_scaffold.py` | `cvFile.ts` limits equal `cv_security.MAX_CV_SIZE` / `ALLOWED_EXTENSIONS`; no service-role key under `web/src` |
| `web/tests/settings-actions.test.mjs` (new), `web/package.json`, `.github/workflows/ci.yml` | Run the real actions against an in-memory fake with `node --test`, as `npm test` and a `web-test` CI job. No new dependency |
| `tests/test_apply_runner.py` | The claim query contains the confirmation rule |
| `scripts/migrate_to_multiuser.py` | Stop overwriting `resume_data` on conflict (section 5) |
| `PRODUCT.md` | Remove the ReportLab and resume-preview claims |

While editing the page, correct three existing false statements: the "Ready for ATS Dispatch" badge shown with no CV, "Download started" / "Upload dialog opened" toasts that do nothing, and "Your uploaded resume is parsed".

---

## 3. Data Flow & Interfaces

### 3.1 Database

```sql
ALTER TABLE users ADD COLUMN IF NOT EXISTS resume_confirmed_at TIMESTAMPTZ;

-- inside protect_user_worker_fields(), in the existing authenticated branch, after the path check
IF NEW.resume_storage_path IS DISTINCT FROM OLD.resume_storage_path
   OR NEW.resume_uploaded_at IS DISTINCT FROM OLD.resume_uploaded_at THEN
    NEW.resume_confirmed_at := NULL;               -- a new CV needs a new review
    IF NEW.auto_apply_mode = 'auto_submit' THEN
        NEW.auto_apply_mode := 'approval_required';
    END IF;
END IF;
IF NEW.auto_apply_mode = 'auto_submit'
   AND (NEW.resume_storage_path IS NULL OR NEW.resume_confirmed_at IS NULL) THEN
    RAISE EXCEPTION 'Confirm your CV before enabling automatic submission';
END IF;
IF NEW.max_daily_applications IS DISTINCT FROM OLD.max_daily_applications
   AND (NEW.max_daily_applications IS NULL OR NEW.max_daily_applications NOT BETWEEN 5 AND 25) THEN
    RAISE EXCEPTION 'max_daily_applications must be between 5 and 25';
END IF;
```

The reset runs before the mode check, so replacing a CV demotes the user instead of raising. Backend writes (`migrate_to_multiuser.py`) are not `authenticated` and are unaffected. An `auto_submit` row that predates the column must be confirmed before that user's next settings save; count such rows before release.

### 3.2 Where each field is stored

| Field | Column / key | Rule |
|---|---|---|
| Full name | `screening_defaults.full_name` (unchanged) | At least two words (on every save, so a confirmed name stays valid); 120 characters max |
| Phone, location | `resume_data.phone`, `resume_data.location` | 120 characters max; empty removes the key |
| LinkedIn, GitHub, portfolio | `resume_data.urls.*` | Must pass `safeHttpUrl`; 300 characters max; empty removes the key |
| Work authorization, sponsorship | `screening_defaults.work_authorization`, `.requires_sponsorship` | Real booleans |
| Years of experience | `screening_defaults.years_experience` | Integer 0-50 |
| Notice period | `screening_defaults.notice_period_days` | Integer 0-365 |
| Mode, cap | `users.auto_apply_mode`, `.max_daily_applications` | Enum; 5-25 |

The two integers must be validated: `map_screening_question` turns an unparseable value into a confident `0`. Every JSONB write merges into the stored object, as `savePreferences` does now. An absent field leaves the stored value alone.

### 3.3 Actions

Each returns `fail(status, { error })` or `{ success, message }`. Demo users get the existing "not stored" message.

| Action | Flow | On failure |
|---|---|---|
| `uploadCv` | `checkCvFile` -> upload new object -> update the 4 `resume_*` columns -> remove old object | Check: 400, nothing written. Upload: old CV stays. Row update: on an error with a code, remove the new object, old CV stays; with no code (connection lost) keep it, because the row may already point at it, and ask for a reload. Old-object removal: log it, still succeed |
| `downloadCv` | `createSignedUrl(path, 60)`, append `&download=<encoded filename>` ourselves (the client's option encodes it twice) -> 303. Plain form, no `use:enhance`, because the target is another origin | Error on the page through the `form` prop |
| `confirmCv` | Check stored values, not unsaved edits (the page shows the stored ones). Require CV, first and last name, both authorization answers -> set `resume_confirmed_at`. Form posts the `resume_uploaded_at` it displayed; the update filters on it | 400 listing missing fields; 409 if the CV changed in another tab |
| `saveAutoApply` | Validate enum and cap -> update | Not confirmed: 400 from a pre-check; the trigger is the backstop |

Content type is derived from the verified extension, not from the browser.

---

## 4. Testing & Verification Strategy

**Automated (no network or database).** Phase 0 uses the existing mocked-cursor and submitter tests. Schema and web rules use the existing static-text tests; these prove the rules are present, not that PostgreSQL runs them correctly. The web tests run the real actions, but their fake copies the trigger rules.

**Manual on staging. Writes to staging, so ask before running:**

| Case | Expected |
|---|---|
| Upload valid PDF, DOCX | Row updated, one object in the folder |
| 2 MB + 1 byte, `.exe` renamed `.pdf`, empty file | 400, nothing stored |
| PATCH `auto_apply_mode=auto_submit` with the anon key, unconfirmed | Trigger error |
| PATCH `max_daily_applications=10000` with the anon key | Trigger error |
| Replace CV while in `auto_submit` | Mode becomes `approval_required`, confirmation cleared |
| Confirm in tab A after replacing in tab B | 409 |
| User B signs a URL for user A's path | Denied by storage RLS |
| Re-run `apply_schema --staging` | No error (idempotent) |

Accessibility: labelled file input and range slider, keyboard-only pass, errors in an `aria-live` region.

```bash
ruff check .
ruff format --check .
mypy models.py config.py scrapers/
python -m scripts.validate_seed_schema
python -m pytest tests/
cd web && npm run check && npm test && npm run build
```

CI runs `npm test` (`web-test`, not a required check). `npm run check` and `npm run build` must be run locally.

---

## 5. Risk Assessment & Safety Circuit Breakers

| Risk | Safeguard |
|---|---|
| Automatic submission with the wrong identity | Phase 0 merges first; confirmation requires first and last name |
| Queued applications sent with a replaced, unreviewed CV | The claim query requires a confirmed CV |
| The claim query needs `resume_confirmed_at` | Apply the schema before any worker runs this code |
| Switching `auto_submit` to `approval_required` does not stop rows already `queued`; the claim query excludes only `disabled` | Say so beside the control: "Choose Paused to stop everything". Moving rows back needs the approval design in #48 |
| New sign-ups have no `users` row (no INSERT policy, no sign-up trigger, and `gdpr_consent_at` is NOT NULL), so `/settings` shows a load error | Separate onboarding issue. Until then this works only for migrated users |
| Host body limit: `adapter-node` defaults to 512 KB; hosting is not chosen (`adapter-auto`) | Set `BODY_SIZE_LIMIT` to at least 3 MB if `adapter-node` is used; test a file just under 2 MB on the real host |
| Worker downloads the old CV while it is being replaced | Download fails into `needs_review`; nothing wrong is sent |
| Malicious CV is stored | Private bucket, owner-only RLS; the worker's `validate_cv` runs before any submission. The user learns only then |
| Re-running `scripts/migrate_to_multiuser.py` resets `resume_data` to `{}` (`ON CONFLICT`), which would now erase saved contact details | Drop `resume_data` from its `DO UPDATE SET` in Phase 1. It already overwrites `screening_defaults` and `profile_filters` the same way; do not re-run it on live users |
| Two tabs saving preferences: last write wins on the JSONB columns | Existing behavior. `confirmCv` is guarded; the rest is accepted |
| Merging to `main` applies `db/schema.sql` to production (`sync-db`) | Additive column and replaced function; test on staging first |

**Constitution check:** 1.1 no new direct connections. 1.2 CV bytes stay in memory. 1.3 and 1.4 untouched. 1.5 strengthened by the database gate.
