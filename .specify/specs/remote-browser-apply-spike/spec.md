# Feature Specification: Remote-Browser Apply Spike (F-hybrid)

**Feature Slug**: `remote-browser-apply-spike`  
**Status**: Approved (2026-11-23)  
**Issue Reference**: #129 (follows PR #126, issue #48)  
**Created**: 2026-11-23  

---

## 1. Problem Statement & User Value

### 1.1 Problem
PR #126 established that JobScanr cannot submit applications server-side: Greenhouse and Lever need the employer's
API key, Ashby enforces Cloudflare Turnstile, and Greenhouse runs reCAPTCHA plus Real Talent fraud detection (IP,
location and cross-applicant pattern signals). Every match is therefore `manual_apply`, and the user retypes the same
details into every form.

### 1.2 Idea under test
A remote browser (Cloudflare Browser Run or Browserbase) opens the employer's own application page and fills it from a
fill plan JobScanr builds from the user's profile and CV. The user watches that browser in a live view embedded in
JobScanr, solves any captcha, reviews every answer, and clicks **Submit** themselves. JobScanr detects the employer's
confirmation page and records the application as Applied.

### 1.3 What this spike is for
**Measurement, not launch.** The spike answers one question: is the hybrid fast and reliable enough to beat manual
apply, and does running from a provider's shared IP ranges trigger captchas or fraud flags often enough to rule it out
in favour of option A (a browser extension on the user's own IP)? Both options share the fill plan, so that work
carries over whichever wins.

### 1.4 Users
- **Job seeker**: one click to open a filled application, then review and Submit.
- **Operator (developer)**: runs the staged tests, reads the metrics, makes the go / no-go call.

---

## 2. Scope & Boundaries

### 2.1 In Scope
1. **Fill plan** (shared with option A): for one application, a list of `{field locator, value, source, confidence}`
   plus the CV, built server-side.
   - Greenhouse: reuse `GreenhouseSubmitter.fetch_questions` and `map_and_validate_payload` (`jobs/apply/`), which
     already read `?questions=true` (a public GET) and map answers with `map_screening_question`.
   - Lever and Ashby: their public APIs give no question schema (PR #126 finding; no Ashby form fetch exists today), so
     the plan is built from the form fields read off the rendered page.
   - Required questions with no confident answer and all open-ended questions are left **empty and highlighted**,
     never guessed.
2. **Remote fill session**: open the posting's apply page in the remote browser, apply the fill plan, attach the CV,
   stop. Never click Submit, never interact with a captcha widget.
3. **Live view handoff**: embed the provider's live view for the owning user only; the user completes the form.
4. **Outcome detection**: per-ATS confirmation detector (URL or page content, defined from pages observed in stage 2);
   on a match the application moves `manual_apply` → `submitted` with an `applied_at` and an event row.
5. **Instrumentation**: per session, record fields planned / filled / corrected by the user, captcha shown (visible
   challenge yes/no), time to submit, outcome, errors. No form values or CV content in the metrics.
6. **Kill switches**: a global flag that stops new sessions and closes open ones, and a per-user daily cap.
7. **Staged test plan** (section 5) and a written results report.

### 2.2 Out of Scope (Pushback)
- **Any automated Submit click**, including "auto-submit when no captcha appears". The user always submits.
- **Captcha solving services, stealth or patched browsers, fingerprint spoofing, residential or rotating proxies.**
  The spike measures the plain provider browser as it is; evading bot controls is not an option at any stage.
- Workday, SmartRecruiters, Teamtailor (accounts, multi-step forms; revisit only if the spike passes).
- LLM-drafted answers for open-ended questions (separate feature; the spike leaves them for the user).
- Batch mode, mobile layout polish, choosing a provider for production (the spike may try both on a small sample).
- Building option A. The spike only produces the shared fill plan and the comparison data.

---

## 3. Functional Requirements

### FR-1 Fill plan
- Input: application id (owned by the requesting user, status `manual_apply`, posting not `stale_closed`).
- Output: fill plan plus a list of fields the user must answer. Building it makes only read-only GETs against the ATS.
- A posting that returns 404 or is closed marks the session `posting_gone` and changes nothing else.

### FR-2 Session start
- Only the owning, signed-in user can start a session for their application, at most one open session per application.
- The global flag and the per-user daily cap are checked before any provider call; refusal is shown to the user.
- The live view URL is short-lived, never logged, never put in a link others can open, and is invalidated when the
  session ends.

### FR-3 Filling
- The CV is sent to the remote browser from memory (no local temp file; constitution §1.2). It does exist inside the
  provider's browser for the session, so the provider is a data processor (see FR-7).
- A field the page does not have, or a value the page rejects, is reported as unfilled, not retried blindly.
- A captcha, login wall, or unexpected page shape stops filling and hands over to the user with a message.
- Session time limit (proposed 10 minutes idle); on expiry the session closes and the application stays `manual_apply`.

### FR-4 Outcome
- Only a confirmation-page match records `submitted`. A closed tab, timeout, error, or the user leaving records nothing
  except the session metrics.
- If the confirmation is ambiguous, the application stays `manual_apply` and the user is asked to mark it.
- A second session on an already `submitted` application is refused (no double submission).

### FR-5 Kill switches
- Global flag off: new sessions refused, open sessions closed within one minute.
- Per-user cap (proposed 5 per day during the pilot).

### FR-6 Metrics
- Stored per session as listed in §2.1 item 5; exportable for the results report.

### FR-7 Privacy
- Users opt in per session with a notice that their details and CV are loaded in a third-party browser service.
- Provider session recordings, if the provider keeps any, are switched off or deleted at session end.

---

## 4. Constitution & Invariant Checks

- [x] Respects database pooler requirements (no new connection path; no connection held during a browser session).
- [x] Respects zero-disk file storage (CV streamed from memory to the remote browser).
- [x] Respects rate limits: fill-plan GETs reuse the existing scraper clients and pacing (Ashby lock included);
      sessions are capped per user and globally.
- [ ] **ATS submission safety gate: needs a constitution amendment.** PR #126's §1.5 says "JobScanr never submits" and
      "only the user records outcomes". Here the user still clicks Submit, but JobScanr fills the employer's form and
      records Applied from the confirmation page. Proposed wording: *JobScanr may fill an employer's form in a browser
      the user watches and controls; the user always clicks Submit; JobScanr may record Applied only from the
      employer's confirmation page.* Needs approval before any live stage. Depends on PR #126 merging first.

---

## 5. Acceptance Criteria

### 5.1 Staged test plan (each stage passes before the next starts)
Live stages send real requests to employers' sites, so each run needs explicit operator confirmation (CLAUDE.local.md).

| Stage | What runs | Submit? | Sample (proposed) |
|---|---|---|---|
| 1. Offline | Playwright against saved copies of real apply pages in CI (saving them is a confirmed, one-off live GET) | Never | 5 per ATS |
| 2. Live fill-only | Fill real postings in the provider browser **and** in a local headed browser on a home connection (baseline), screenshot, close | Never | 30 Greenhouse, 15 Lever, 15 Ashby |
| 3. Consenting submits | Full flow on postings whose owner agreed: a Greenhouse or Lever sandbox, or a cooperating employer | Yes, by a person | ≥ 10 |
| 4. Pilot | Opted-in real users on real matches, caps and kill switch on | Yes, by the user | ≤ 5 users, 2 weeks |

Never submit to boards the tester does not own or have permission for (for example `jobs.lever.co/leverdemo`).

**Amended 2026-11-26 (user decision after stage 2):** stage 3 is dropped. No Greenhouse, Lever or Ashby sandbox is
available without a partner agreement, and JobScanr never submits: the user checks every value in the live view and
clicks Submit, so a separate test stage adds little over that review. Stage 4 starts with one user, the owner, on
genuine applications they want to make, which also covers stage 3's checks (each application recorded once, on the
right row, with the values the user saw). The "zero wrong submissions" gate is read over those applications. Opening
the pilot to other users needs a fresh decision on a consented check first.

### 5.2 Go / no-go gates (thresholds proposed; confirm before stage 2)
- **Zero wrong submissions**: no submission to the wrong posting, no duplicate, no value the user did not see.
- **Fill accuracy** ≥ 95% of required fields filled correctly on Greenhouse in stage 2, with Lever and Ashby reported.
  Amended 2026-11-26 (user decision after stage 2): measured over the fields JobScanr is meant to fill (contact
  fields, CV, planned answers), not every required control; questions left for the user, including Greenhouse's
  location autocomplete, are not counted.
- **Visible-captcha rate** from the provider browser ≤ 20%, and no more than 10 points above the home-connection baseline.
- **Time to submit** (pilot median) at least 50% below the manual baseline measured in stage 2.
- **Response parity** (pilot, reported only): employer responses to hybrid applications are not visibly lower than
  to the same users' manual ones. Too small a sample to gate on; recorded for the decision.

A failed gate ends the spike with a report; the fill plan still feeds option A.

### 5.3 Tests and quality
- Unit tests for the fill plan builder (mapped, unmapped, open-ended, closed posting) with `httpx.MockTransport`.
- Unit tests for session start refusals (wrong owner, cap, global flag, already submitted) and confirmation detection.
- Stage 1 Playwright tests run in CI with no network.
- `ruff check .`, `ruff format --check .`, `mypy`, and `python -m pytest tests/` pass.

### 5.4 Deliverable
`docs/remote_browser_apply_spike.md`: per-stage metrics, provider comparison, the go / no-go decision, and the
recommendation between this hybrid and option A.
