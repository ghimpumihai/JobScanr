# Feature Specification: Applications Tracker

**Feature Slug**: `applications-review-dashboard` (kept from the first version)  
**Status**: Approved (2026-11-23)  
**Issue Reference**: #48 (re-scoped, see section 2)  
**Created**: 2026-11-22  
**Amended**: 2026-11-23. Replaces the version approved on 2026-11-22, whose automatic submission cannot work (section 1.1)  

---

## 1. Problem Statement & User Value

### 1.1 Problem Statement
Task 0.2 found, from each vendor's own API documentation on 2026-11-23, that **Greenhouse and Lever accept applications only with the employer's API key**. A job seeker cannot get one, so JobScanr cannot submit anywhere. Lever's public postings also carry no questions. Evidence is in `plan.md` section 5. The rest of this list is read from the code.

1. **Applications are stuck.** The pipeline stages Greenhouse and Lever matches as `queued` or `pending_approval`, which nothing can ever send, and nothing moves them on.
2. **Pages promise what cannot happen.**
   - Settings offers "Automatic submission", a daily limit, and a CV confirmation that exists only to enable automatic submission.
   - Matches offers "Queue" and "Queue all", which fail.
   - Applications says "approved and queued" without doing anything, shows an internal token as the employer's confirmation, and shows invented answers in its drawer.
3. **Applying by hand is not tracked.** A user cannot record that they applied, or that a role does not interest them.
4. **Closed postings never leave the list.** Only the worker closes an application, and it does not run.
5. **The digest invents confirmation IDs** (`APP-<id>`).

### 1.2 User Value
- **Job seeker**: one list of roles to apply to, with their details ready to copy and the posting one click away; a record of where they applied.

### 1.3 Expected Outcome
Every matched role appears under To Apply. The user applies on the employer's site, marks it Applied, or marks it Not Interested. No page claims JobScanr submits anything.

---

## 2. Scope & Boundaries

### 2.1 In Scope
- Applications page: tabs, filters, manual-apply drawer, Mark as Applied, Not Interested, undo.
- Pipeline: stage every match as To Apply; close applications whose posting has gone.
- Remove the false promises in Settings, Matches, Applications and the digest.
- Database rule for the status changes a user may make.

### 2.2 Out of Scope (Pushback)

| Item | Reason |
|---|---|
| Automatic submission, approval, review drawer, stored answers (#48) | Needs employer API keys (1.1). The approved plan for them is withdrawn |
| Emergency kill switch (#48) | Nothing is sent. Paused in Settings still stops matching and digests |
| Real-time updates (#48) | Nothing changes between pipeline runs except the user's own actions |
| Job description in the drawer (#48) | Constitution 1.3: never stored. The drawer links to the posting |
| Copying work history or an address (#48) | Not stored. Location is copied instead |
| Deleting the worker and the Greenhouse and Lever submitters | Separate issue (D4) |
| Browser automation of employer forms | CAPTCHAs, site terms, and constitution 1.5 |
| Linking the digest to the dashboard | No public web address is configured |

### 2.3 Decisions (defaults approved 2026-11-23)

| ID | Decision | Alternative not chosen |
|---|---|---|
| D1 | Add Not Interested, and allow undo of it and of Applied | No dismissal: To Apply keeps every match ever found |
| D2 | Settings keeps only Active and Paused. The automatic option, daily limit and CV confirmation step go, and the database refuses `auto_submit` | Leave them, labelled unavailable |
| D3 | An application whose posting the scanner has not seen for 30 days moves to Closed. That is the same age at which unreferenced postings are already deleted | Never close; the user dismisses them |
| D4 | Leave the worker and submitter code in place, unused, and open an issue to delete it | Delete it now: a much larger change |
| D5 | Matches shows "Apply" (a link to the posting) for every platform, as it already does for Workday, and drops "Queue all" | Keep the buttons, which only report an error |

---

## 3. Functional Requirements

### FR-1: Statuses

| Tab | Status | Set by |
|---|---|---|
| To Apply | `manual_apply` | Pipeline, for every match on every platform while the user is not Paused |
| Applied | `submitted` | The user |
| Not Interested | `dismissed` (new) | The user |
| Closed | `stale_closed` | Pipeline (FR-6) |

- Existing `queued`, `pending_approval`, `needs_review`, `failed` and `submitting` rows become `manual_apply` when the schema is applied. The production `users` table was empty on 2026-11-22, so this affects only staging.
- Nothing new is ever staged as `queued` or `pending_approval`.

### FR-2: Applications page
- Tabs with counts. Columns: job title, company, platform, added on, applied on, action.
- **Applied on** is the time the user marked it. There is no confirmation ID column: no employer returns one.
- Filters: platform (all seven), company name (contains), added or applied date range. Tab and filters live in the URL, so reload and Back keep them.
- Newest first, 50 rows per page. Counts cover all matching rows.
- A Closed row says when the posting was last seen.

### FR-3: Apply drawer
- Opens from To Apply and Closed.
- Shows job title, company, location and platform, and a link to the posting (`http(s)` only; otherwise no link and a notice).
- Copy buttons for name, email, phone, location, LinkedIn, GitHub and portfolio, from Settings. Empty fields have no button. If copying fails, the value stays visible and selectable.
- A button downloads the user's CV, using the existing Settings download. If no CV is stored, it links to Settings instead.
- No invented content: a missing value reads "Not set". Employer text is shown as plain text.

### FR-4: Status changes

| Action | From | To |
|---|---|---|
| Mark as Applied | To Apply, Closed | Applied |
| Not Interested | To Apply, Closed | Not Interested |
| Undo | Applied (marked by the user), Not Interested | To Apply |

- Each change shows the result and an Undo button. No confirmation prompt, because each change can be undone.
- Each change checks the row's current status first. A second tab or double click changes nothing and reports "already changed".
- Each change writes one `application_events` row.
- The database allows a signed-in user only these changes, only on their own rows. Every other change a signed-in user makes to `applications` is rejected, whatever client sent it.

### FR-5: Pipeline staging
- A match is staged as `manual_apply` on every platform, while the user is not Paused, as other platforms are today.
- Rows that already exist are left alone, including Applied and Not Interested.

### FR-6: Closing
- Each pipeline run moves `manual_apply` rows whose posting was last seen over 30 days ago to `stale_closed`, with one event each.
- It never touches Applied or Not Interested rows.

### FR-7: Removing false promises
- **Settings:** modes "Active" (matches and digests) and "Paused" (no matching, no digest). The automatic option, daily limit, CV confirmation button and badge, and the text tying the CV to automatic submission are removed. The database refuses `auto_submit` from a signed-in user.
- **Matches:** "Apply" opens the posting for every platform; "Queue all" is removed.
- **Applications:** no toast, receipt or drawer text claims a submission, a queue, a worker or a verification.
- **Digest:** an application marked by the user reads "marked as applied by you", never `APP-<id>`.

### FR-8: Errors and demo mode
- Every failure shows a specific message in an `aria-live` region; a success message appears only after the database confirms the change.
- If the connection drops during a change, the page says the outcome is unknown and reloads the row.
- Demo sessions use demo rows, store nothing and say so. Real users never see demo content.

---

## 4. Constitution & Invariant Checks

- [x] **Database pooler (1.1)**: one new pipeline query on the existing pool; no request is made while it is held.
- [x] **Zero-disk files (1.2)**: the CV download reuses the existing signed link; nothing is written to disk.
- [x] **Descriptions (1.3)**: none stored or shown.
- [x] **Scrapers (1.4)**: untouched; closing uses the existing `last_seen_at`.
- [ ] **ATS safety gate (1.5)**: must be rewritten. No platform supports submission without an employer key, so every platform is manual. **Ask first** before editing the constitution.

---

## 5. Acceptance Criteria

| ID | Criterion | Proof |
|---|---|---|
| AC-1 | A match on each platform is staged as `manual_apply`; existing rows are unchanged; a Paused user gets none | Unit test (SQL and pipeline) |
| AC-2 | Applying the schema converts the old statuses, keeps all others, and succeeds twice | Static schema test; staging |
| AC-3 | A posting last seen 31 days ago closes its To Apply row; 29 days does not; Applied and Not Interested rows never change | Unit test (SQL text); staging |
| AC-4 | Each change in FR-4 works and writes one event; undo restores To Apply | Web test; staging |
| AC-5 | A signed-in user cannot make any other status change, change any other column, or change another user's row; an anonymous user can change nothing | Static schema test; staging |
| AC-6 | Two tabs making the same change give one change and one event | Staging |
| AC-7 | Each tab, filter and count is right with more than 50 rows; reload and Back keep them | Web test (query); staging |
| AC-8 | Copy buttons appear only for saved values; the CV download works, or links to Settings when no CV is stored | Web test; manual |
| AC-9 | A `javascript:` posting URL is not linked; employer text containing HTML is shown as text | Web test; manual |
| AC-10 | Settings offers only Active and Paused; a direct API update to `auto_submit` is rejected | Web test; static schema test; staging |
| AC-11 | No page or digest text claims automatic submission, queueing, a receipt, a confirmation ID or verified answers | Scaffold test (banned strings); review in the page |
| AC-12 | Matches shows Apply links for every platform and no Queue buttons | Scaffold test; manual |
| AC-13 | A lost connection during a change says the outcome is unknown; demo changes store nothing | Web test |
| AC-14 | The page works by keyboard only, at phone width; controls are labelled; messages are in `aria-live` | Manual (no screen reader check) |
| AC-15 | `ruff`, `ruff format --check`, `mypy`, seed validation, `pytest`, `npm run check`, `npm test` and `npm run build` pass | Commands |

Unit tests use mocks only. Staging checks write to staging and need approval first. No database runs in CI, so database rules are proven only by the staging runs.
