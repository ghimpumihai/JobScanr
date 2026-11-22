# Feature Specification: CV Upload, Candidate Details & Auto-Apply Controls

**Feature Slug**: `profile-preferences-ui`  
**Status**: Converged (2026-11-22)  
**Issue Reference**: #47 (narrowed, see section 2)  
**Created**: 2026-11-22  
**Amended**: 2026-11-22 after first approval: FR-1, FR-2, FR-4, FR-5, AC-2, AC-3, AC-10, AC-11, AC-15, AC-16, AC-17, new AC-18  

---

## 1. Problem Statement & User Value

### 1.1 Problem Statement
The `/settings` page stores search filters, a name and a work authorization answer, but a candidate cannot prepare or control an application from it:
1. The CV buttons only show a message. Nothing is uploaded or downloaded, yet the page says "Ready for ATS Dispatch".
2. Phone, location, profile links, sponsorship, years of experience and notice period cannot be entered, so screening questions that need them go to `needs_review`.
3. The auto-apply mode and daily cap cannot be set in the page, but any signed-in user can set them to any allowed mode and any number through the Supabase API, with no CV review.
4. The worker builds applications without the user's email and ignores the name saved on this page (reproduced offline: name "Candidate", empty email).

### 1.2 User Value
- **Job seeker**: uploads their own CV, fills in the details applications need, and decides when and how much is submitted.
- **Apply worker**: receives a real name, email, contact details and a reviewed CV.

### 1.3 Expected Outcome
A candidate with a `users` row can go from no CV to a confirmed CV with auto-apply controls on one page. The worker sends no application without a confirmed CV.

---

## 2. Scope & Boundaries

### 2.1 In Scope
- CV upload, replacement and download (PDF, DOCX, DOC; 2 MB).
- Contact details: name, phone, location, LinkedIn, GitHub, portfolio.
- Screening defaults: work authorization, sponsorship, years of experience, notice period.
- CV confirmation, enforced in the database.
- Auto-apply mode and daily cap (5-25).
- Worker identity fix (a prerequisite, separate PR).

Already delivered by #46 and unchanged: titles, levels, locations and excluded keywords.

### 2.2 Out of Scope (Pushback)

| Issue #47 item | Reason |
|---|---|
| CV parsing, `/api/cv/parse` (D1) | No parser or Python HTTP service exists. It would prefill about five fields. Manual entry is the issue's own fallback |
| ReportLab "Download Test PDF", ATS resume preview (D2) | Superseded by `cv-storage-security`: the original file is submitted |
| Education, experience and skills editor (D2) | Superseded by `web-scaffold-navigation`; nothing reads those fields |
| Separate `/profile`, `/settings/preferences`, `/settings/auto-apply` pages (D2) | Superseded: one `/settings` page |
| Changing what `disabled` does in the backend (D3) | It is labelled accurately instead (FR-5) |

Also out: creating `users` rows at sign-up, approving queued applications (#48), deleting a CV without replacing it, and scanning for malware at upload time (the worker scans before each submission).

D1-D3 defaults were approved on 2026-11-22.

---

## 3. Functional Requirements

### FR-1: CV file
- Accept `.pdf`, `.docx`, `.doc` up to 2 MB whose first bytes match the extension. Reject anything else, storing nothing.
- A successful upload replaces the previous CV; one active file per user. If the upload or the row update definitely fails, the previous CV and its confirmation stay in effect. If the connection drops during the row update, the outcome is unknown: the new file is kept, so the row never points at a deleted file, and the user is told to reload.
- Download returns the stored file under its cleaned upload name (no path, no invisible characters, 120 characters max) through a link valid for 60 seconds.
- The card shows one of: no CV, needs confirmation, confirmed. It reflects a new upload without a manual reload.

### FR-2: Candidate details
- Full name: at least two words, 120 characters max. Also enforced on later edits, so a confirmed user cannot end up with an empty last name.
- Phone and location: optional, 120 characters max. Links: optional, `http(s)` only, 300 characters max. Clearing one removes it.
- Location must not be stored in `screening_defaults`, where it answers unrelated questions ("relocation").

### FR-3: Screening defaults
- Work authorization and sponsorship are stored as booleans; there is no pre-selected answer.
- Years of experience: integer 0-50. Notice period: integer 0-365 days. Both optional; invalid values are rejected, never stored as 0.

### FR-4: Confirmation
- Requires a CV, a full name, and both authorization answers. The page shows the **saved** values being confirmed; unsaved edits do not count.
- If the CV changed since the page loaded, confirmation is refused.
- Replacing the CV clears the confirmation and changes `auto_submit` to `approval_required`.
- The worker claims an application, in any mode and however it was queued, only while the user's CV is confirmed. Applications already queued when a CV is replaced wait for the new confirmation.
- The database enforces that a confirmation exists; the required-details check is in the web app. A user calling the API directly can confirm their own CV without it.

### FR-5: Auto-apply controls

| Mode | Label must say |
|---|---|
| `approval_required` | Matches and digests continue; nothing new is submitted automatically |
| `auto_submit` | Eligible Greenhouse and Lever applications are queued for submission. Needs a confirmed CV |
| `disabled` | Paused: no matching, no digest, no applications |

- Beside the modes: applications already queued are still sent unless Paused is chosen (and while the CV is confirmed, FR-4).
- Daily cap: integer 5-25.
- The database rejects an authenticated user's update that leaves `auto_submit` without a confirmed CV, or changes the cap to a value outside 5-25, whatever client sent it.

### FR-6: Worker identity
- Submissions carry the user's account email and their saved name. `resume_data` names take precedence over the name saved on this page.

### FR-7: Errors and demo mode
- Every failure shows a specific message in an `aria-live` region and leaves stored data unchanged, except that a failed cleanup may leave an unused file.
- Saving one group of fields never erases another. Demo sessions store nothing and say so.

---

## 4. Constitution & Invariant Checks

- [x] **Database pooler (1.1)**: no new direct connections; the claim query still releases its connection before any HTTP call.
- [x] **Zero-disk files (1.2)**: CV bytes stay in memory.
- [x] **Descriptions and scrapers (1.3, 1.4)**: untouched.
- [x] **ATS safety gate (1.5)**: conditional submission rules are unchanged; a confirmation gate is added before `auto_submit`.

Re-checked against the code by `/spec-converge` on 2026-11-22.

---

## 5. Acceptance Criteria

| ID | Criterion | Proof |
|---|---|---|
| AC-1 | A valid PDF, DOCX and DOC each upload, download under the original name, and leave exactly one object in the user's folder | Staging |
| AC-2 | 2 MB + 1 byte, an empty file, a wrong extension and a renamed `.exe` are rejected and nothing is stored | Web test; staging; limits equal `cv_security.py` by test |
| AC-3 | If the row update definitely fails after the new file is uploaded, the old CV and confirmation still apply; after a dropped connection the row never points at a deleted file | Web test |
| AC-4 | User B cannot get a download link for user A's CV | Staging |
| AC-5 | Each FR-2 and FR-3 field survives a reload; invalid values are rejected; clearing an optional contact field removes it | Staging |
| AC-6 | A one-word name is refused, including after confirmation | Staging |
| AC-7 | Saving details keeps unrelated keys in `resume_data`, `screening_defaults` and `profile_filters` | Staging |
| AC-8 | Confirmation is refused when a requirement is missing, and when the CV was replaced in another tab | Staging |
| AC-9 | Upload then confirm works without reloading the page | Staging |
| AC-10 | A direct API update to `auto_submit` without confirmation, or to a cap of 4, 26 or NULL, is rejected | Static schema test; staging (passed 2026-11-22, rolled back) |
| AC-11 | Replacing the CV in `auto_submit` clears the confirmation and sets `approval_required` | Static schema test; staging (passed 2026-11-22, rolled back) |
| AC-12 | Mode labels and the queued-applications note match FR-5; `auto_submit` cannot be selected before confirmation | Review in the page |
| AC-13 | Greenhouse and Lever payloads contain the account email and the web-saved name | Unit test |
| AC-14 | No false status, toast or "is parsed" text remains | Review in the page |
| AC-15 | The page works by keyboard only; inputs are labelled; errors appear in an `aria-live` region | Manual (no screen reader check) |
| AC-16 | Applying the schema twice succeeds; re-running the migration script does not change `resume_data` | Staging (schema passed 2026-11-22); unit test (script) |
| AC-17 | `ruff`, `ruff format --check`, `mypy`, seed validation, `pytest`, `npm run check`, `npm test` and `npm run build` pass; no service-role key under `web/src` | Commands; unit test |
| AC-18 | The worker does not claim a queued application while the user's CV is unconfirmed | Unit test (query text); staging |

Unit tests use mocks only. Staging checks write to staging and need approval first. No database runs in CI, so database rules are proven only by the staging runs.
