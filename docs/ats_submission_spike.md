# ATS Unauthenticated Submission Spike Report

> **Issue Reference**: #49 (Spike: Test Real Unauthenticated Submissions on Greenhouse, Lever, Ashby, SmartRecruiters, Teamtailor)  
> **Target Downstream Dependency**: Issue #51 (Greenhouse and Lever Submitters with Question Schema Mapping)  
> **Date**: October 2026  
> **Status**: COMPLETED & VERIFIED

---

## 1. Executive Summary & Feasibility Score Matrix

This spike investigated the mechanics, feasibility, and failure modes of unauthenticated public job application dispatch across the major Applicant Tracking Systems (ATS) tracked by JobScanr: **Greenhouse**, **Lever**, **Ashby**, **SmartRecruiters**, and **Teamtailor**.

### Feasibility Score Taxonomy
1. **Full / Conditional Automation (Direct HTTP POST)**:
   - Endpoint accepts unauthenticated public submissions with multipart/form-data.
   - Automation works reliably *unless* dynamic bot detection (reCAPTCHA/Turnstile) is explicitly enforced by the employer's board configuration.
2. **Manual Apply Fallback Required (`manual_apply`)**:
   - The platform strictly requires authenticated employer/partner API keys for applicant dispatch, OR enforces mandatory client-side bot challenges (Cloudflare Turnstile, DataDome) that cannot be cleanly solved over headless HTTP POST.
   - System flags the job as `manual_apply` and provides the applicant with pre-filled fields or one-click copy helpers.

### ATS Platform Feasibility Matrix

| ATS Platform | Public Dispatch Endpoint | Auth Required | File Field | Bot / Captcha Protection | Feasibility Classification | Architecture Action (Issue #51) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Greenhouse** | `POST https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{id}` | None (Public Board) | `resume` (PDF) | reCAPTCHA (optional per company) | **Conditional Automation** | Automate when captcha absent & questions 100% mapped; fallback to `manual_apply` if captcha triggered. |
| **Lever** | `POST https://api.lever.co/v0/postings/{company}/{id}` | None (Public Board) | `resume` (PDF) | reCAPTCHA/hCaptcha (optional per company) | **Conditional Automation** | Automate when captcha absent & questions 100% mapped; fallback to `manual_apply` if captcha triggered. |
| **Ashby** | `POST https://jobs.ashbyhq.com/api/non-user-graphql` (`submitApplication`) | None (GraphQL) | Multi-step S3 upload (`fileHandle`) | **Cloudflare Turnstile (Mandatory)** | **Manual Apply Fallback** | Flag as `manual_apply`. Prefill profile helper for user. Avoid brittle Turnstile bypass. |
| **SmartRecruiters** | `POST https://api.smartrecruiters.com/v1/companies/{co}/postings/{id}/candidates` | **Yes** (`X-SmartToken`) | Multipart/JSON | DataDome / CSRF on web apply portal | **Manual Apply Fallback** | Flag as `manual_apply`. Direct API dispatch rejected without employer token. |
| **Teamtailor** | `POST https://api.teamtailor.com/v1/job-applications` | **Yes** (`Token token=...`) | JSON:API document | Rails authenticity token & CSRF on web portal | **Manual Apply Fallback** | Flag as `manual_apply`. Direct API dispatch rejected without employer token. |

---

## 2. Greenhouse (Boards API v1)

Greenhouse provides a public Job Board API allowing third-party sites and candidate portals to inspect job openings and submit applications directly without partner API keys.

### 2.1 Endpoints & HTTP Methods
- **Inspect Job & Question Schema**:
  ```http
  GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}?questions=true
  Accept: application/json
  ```
- **Submit Application**:
  ```http
  POST https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}
  Content-Type: multipart/form-data
  ```

### 2.2 Question Schema Structure
Requesting `?questions=true` returns a `questions` array. Each question object contains:
- `id`: Unique integer identifier (e.g. `12345678`).
- `label`: Display text for the question (e.g. *"Are you legally authorized to work in the United States?"*).
- `required`: Boolean indicating whether the field must be supplied.
- `fields`: Array of form fields. Key field types:
  - `input_text`: Single-line text input -> mapped to form field `question_{id}`.
  - `textarea`: Multi-line text input -> mapped to form field `question_{id}`.
  - `multi_value_single_select`: Dropdown / radio options with `values` (each with `value` string or id).
  - `multi_value_multi_select`: Multi-select checkboxes -> mapped to `question_{id}[]`.
  - `input_file`: Additional file attachment -> multipart file stream.

### 2.3 Multipart Payload Specification
A Greenhouse submission must be formatted as `multipart/form-data`:

```text
--BOUNDARY
Content-Disposition: form-data; name="first_name"

Jane
--BOUNDARY
Content-Disposition: form-data; name="last_name"

Doe
--BOUNDARY
Content-Disposition: form-data; name="email"

jane.doe@example.com
--BOUNDARY
Content-Disposition: form-data; name="phone"

+1-555-0199
--BOUNDARY
Content-Disposition: form-data; name="resume"; filename="Jane_Doe_Resume.pdf"
Content-Type: application/pdf

<binary PDF stream>
--BOUNDARY
Content-Disposition: form-data; name="question_987654"

Yes
--BOUNDARY
Content-Disposition: form-data; name="mapped_url_token"

stripe
--BOUNDARY--
```

### 2.4 reCAPTCHA & Cloudflare Challenges
- **Dynamic reCAPTCHA Injection**: Greenhouse enables account administrators to toggle Google reCAPTCHA v2 / Enterprise on job boards.
- **Form Param**: When active, Greenhouse expects `g-recaptcha-response` (or `recaptcha_response`).
- **Response when Captcha Missing/Invalid**:
  - HTTP `400 Bad Request` or `422 Unprocessable Entity`.
  - JSON body: `{"error": "Invalid captcha"}` or `{"message": "Captcha response is required"}`.
- **Routing Decision**: If Greenhouse returns a captcha error, the submitter immediately records `status="manual_apply"` and `reason="captcha_blocked"`.

### 2.5 HTTP Response Codes
- `200 OK` / `201 Created`: Application accepted. Response contains candidate/application ID or confirmation redirect URL.
- `400 Bad Request` / `422 Unprocessable Entity`: Validation failure (missing required field, unmapped question, or captcha required).
- `404 Not Found`: Job closed or invalid board token.
- `429 Too Many Requests`: Rate limit exceeded on Greenhouse board endpoint.

---

## 3. Lever (Postings API v0)

Lever offers an unauthenticated public Postings API historically designed for embedding career page widgets and direct application forms.

### 3.1 Endpoints & HTTP Methods
- **Inspect Posting Details & Custom Cards**:
  ```http
  GET https://api.lever.co/v0/postings/{company}/{job_id}?mode=json
  Accept: application/json
  ```
- **Submit Application**:
  ```http
  POST https://api.lever.co/v0/postings/{company}/{job_id}
  Content-Type: multipart/form-data
  ```
  *(Optional query param: `?silent=true` suppresses employer auto-acknowledgement emails).*

### 3.2 Standard Fields & Parameter Specifications
- `name` (string, **required**): Candidate's full name (Lever does NOT split first and last names).
- `email` (string, **required**): Candidate's email address.
- `phone` (string, optional/required): Candidate phone number.
- `org` (string, optional): Current organization/employer.
- `urls[LinkedIn]` (string, optional): LinkedIn profile URL.
- `urls[GitHub]` (string, optional): GitHub profile URL.
- `urls[Portfolio]` (string, optional): Portfolio / personal site.
- `urls[Twitter]` (string, optional): Twitter / X profile.
- `urls[Other]` (string, optional): Other links.
- `comments` (string, optional): Cover letter text or additional notes.
- `resume` (file, **required**): Binary resume stream. **Crucial**: The multipart field name MUST be `resume`, not `file` or `cv`.

### 3.3 Custom Questions & Cards
Lever structures custom screening questions within `cards`:
- In posting JSON, `cards` contains question items with IDs and field definitions.
- Submitted in multipart as:
  - `cards[{card_id}][field0]`: answer string or option value.
  - `cards[{card_id}][field1]`: answer string or option value.
- Consent questions:
  - `consent[marketing]`: `"true"` or `"false"`
  - `consent[data-retention]`: `"true"` or `"false"`

### 3.4 Bot Detection & reCAPTCHA
- Lever injects reCAPTCHA or hCaptcha dynamically based on employer configuration and request risk profiling.
- Field: `g-recaptcha-response` or `h-captcha-response`.
- Failure response: HTTP `400 Bad Request` with `{"ok": false, "error": "Captcha verification failed"}`.
- Routing Decision: Transitions to `manual_apply`.

### 3.5 HTTP Response Codes
- `200 OK`: `{"ok": true, "applicationId": "...", "redirect": "..."}`
- `400 Bad Request`: `{"ok": false, "error": "Missing required field: resume"}`
- `404 Not Found`: Posting unlisted or invalid company identifier.
- `429 Too Many Requests`: Rate limited.

---

## 4. Ashby (Public GraphQL API)

Ashby does NOT provide an unauthenticated public REST endpoint for candidate applications. All candidate applications on `jobs.ashbyhq.com` flow through their non-user GraphQL endpoint.

### 4.1 Endpoint & Flow
- **Endpoint**:
  ```http
  POST https://jobs.ashbyhq.com/api/non-user-graphql
  Content-Type: application/json
  ```
- **Flow**:
  1. **Schema Fetch**: `ApiJobPostingWithApplicationForm` query returns `applicationForm` definition.
  2. **File Upload Step**: Ashby does NOT accept inline multipart resume uploads in `submitApplication`. Candidates must first request a presigned S3 upload URL, stream the binary file to S3, and retrieve a `fileHandle`.
  3. **Mutation Execution**:
     ```graphql
     mutation SubmitApplication(
       $organizationHostedJobsPageName: String!
       $jobPostingId: String!
       $applicationFormValues: JobPostingApplicationFormValuesInput!
       $turnstileToken: String
     ) {
       submitApplication(
         organizationHostedJobsPageName: $organizationHostedJobsPageName
         jobPostingId: $jobPostingId
         applicationFormValues: $applicationFormValues
         turnstileToken: $turnstileToken
       ) {
         applicationId
         success
       }
     }
     ```

### 4.2 Bot Challenges: Cloudflare Turnstile
- **Turnstile Enforcement**: Ashby enforces Cloudflare Turnstile (`turnstileToken`) on the `submitApplication` mutation across all public hosted job boards.
- **Anti-Bot Verification**: Without a valid client-side Turnstile token verified by Cloudflare, the GraphQL mutation returns `errors: [{"message": "Turnstile verification failed"}]`.
- **Soft-Throttling**: As established in `scrapers/ashby.py`, Ashby soft-throttles bursts by returning HTTP 200 with `null` data or GraphQL errors rather than standard 429s.

### 4.3 Feasibility & Architecture Decision
- **Feasibility Classification**: **Manual Apply Fallback Required (`manual_apply`)**.
- **Rationale**: Headless HTTP POST cannot generate valid Cloudflare Turnstile tokens. Running headless browser automation (Playwright/Puppeteer) or reverse-engineering Turnstile is fragile, high-maintenance, slow, and breaches terms.
- **Contract for Issue #51**: All Ashby postings will be routed to `manual_apply` with candidate details pre-filled in a clipboard/export helper.

---

## 5. SmartRecruiters

### 5.1 Endpoint & Authentication Restrictions
- **Candidate Submission API**:
  ```http
  POST https://api.smartrecruiters.com/v1/companies/{company}/postings/{posting_id}/candidates
  ```
  - **Authentication**: **Strictly Required**. Requires `X-SmartToken: <api_key>` or OAuth 2.0 Bearer Token.
  - An unauthenticated request immediately returns `401 Unauthorized` or `403 Forbidden`.
- **Public Career Portal Apply Web Form**:
  `https://jobs.smartrecruiters.com/{company}/{posting_id}/apply`
  - Utilizes internal endpoints requiring session cookies, CSRF tokens (`X-CSRF-Token`), and DataDome bot challenge verification.
  - Headless HTTP submission without partner credentials is not supported.

### 5.2 Feasibility & Architecture Decision
- **Feasibility Classification**: **Manual Apply Fallback Required (`manual_apply`)**.
- **Contract for Issue #51**: All SmartRecruiters postings are flagged as `manual_apply`.

---

## 6. Teamtailor

### 6.1 Endpoint & Authentication Restrictions
- **Job Applications API**:
  ```http
  POST https://api.teamtailor.com/v1/job-applications
  ```
  - **Authentication**: **Strictly Required**. Requires `Authorization: Token token=<API_KEY>` and `X-Api-Version: 20210218`.
  - Unauthenticated calls return `401 Unauthorized`.
- **Public Career Portal Web Form**:
  `https://{company}.teamtailor.com/jobs/{id}/apply`
  - Server-rendered Rails application requiring CSRF authenticity tokens, session cookies, and dynamic anti-bot protection.

### 6.2 Feasibility & Architecture Decision
- **Feasibility Classification**: **Manual Apply Fallback Required (`manual_apply`)**.
- **Contract for Issue #51**: All Teamtailor postings are flagged as `manual_apply`.

---

## 7. Architecture Contract for Issue #51 (Implementation Spec)

Based on this spike, the downstream implementation for Issue #51 must adhere to the following contracts:

### 7.1 Scope of Automated Submitters
- Build submitters **ONLY** for:
  1. `jobs/apply/greenhouse.py` (`GreenhouseSubmitter`)
  2. `jobs/apply/lever.py` (`LeverSubmitter`)
- Route all other platforms (**Ashby**, **SmartRecruiters**, **Teamtailor**, **Workday**, **Google**) directly to `manual_apply`.

### 7.2 Safety Decision Gate & State Machine
Every application candidate passes through the following state machine before network submission:

```text
[Candidate Match Found]
        │
        ▼
[Fetch ATS Question Schema] (GET Greenhouse / Lever)
        │
        ├──> [Detects Bot Challenge (Captcha/Turnstile)] ──> [manual_apply (captcha_blocked)]
        │
        ├──> [Parse Required Screening Questions]
        │         │
        │         ├──> 100% Confidently Mapped to Profile ──> [auto_submit]
        │         │                                                │
        │         │                                                ▼
        │         │                                          [POST Application]
        │         │                                                │
        │         │                                                ├──> 200/201: [SUBMITTED]
        │         │                                                └──> 400 Captcha: [manual_apply]
        │         │
        │         └──> Unmapped / Ambiguous / Essay Question ──> [needs_review]
        │
        └──> [Job Closed / 404] ──> [EXPIRED]
```

### 7.3 Screening Question Mapping Rules
1. **Work Authorization**: Mapped against `user.screening_defaults.work_authorization` (Yes/No, US Citizen, EU Citizen, etc.).
2. **Visa Sponsorship**: Mapped against `user.screening_defaults.requires_sponsorship` (Yes/No).
3. **Years of Experience**: Parsed numeric regex mapped against `user.screening_defaults.years_of_experience`.
4. **Notice Period**: Mapped against `user.screening_defaults.notice_period_weeks`.
5. **Location / Remote**: Mapped against `user.screening_defaults.current_location`.
6. **Open-Ended / Essay Questions**: Any required question with free-form textarea (>100 characters) or unmapped radio options MUST trigger `needs_review` rather than guessing.

### 7.4 In-Memory PDF Resume Lifecycle
- Resume PDF is compiled in-memory via ReportLab (`io.BytesIO`) as specified in Issue #50.
- Streamed directly to `httpx.AsyncClient` multipart dictionary:
  `files={"resume": ("Resume.pdf", pdf_stream.getvalue(), "application/pdf")}`.
- Zero disk writes, zero persistent temporary files.
- SHA-256 checksum calculated on `pdf_stream.getvalue()` before dispatch for audit logging.

---

## 8. Verification & Test Scripts

A standalone test script is provided in `scripts/spike_test_submissions.py` and unit tested in `tests/test_spike_submissions.py`.

It supports:
- `--inspect`: Inspects question schema or endpoint contract for a given board.
- `--dry-run`: Builds the complete multipart payload, validates all fields, and outputs the exact `curl` command.
- `--report`: Displays the feasibility matrix and platform contracts.
- `--test-submission`: Optional live verification (guarded by explicit `--confirm-live-test` flag).
