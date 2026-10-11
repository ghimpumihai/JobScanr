# Feature Specification: Greenhouse and Lever Submitters with Question Schema Mapping

**Feature Slug**: `greenhouse-lever-submitters`  
**Status**: Draft  
**Issue Reference**: #51 (Downstream of #49, #63; Upstream of #52, #48)  
**Created**: 2026-10-11  

---

## 1. Problem Statement & User Value

### 1.1 Problem Statement
Job seekers must spend extensive time manually filling out redundant application forms on company career portals. For public boards hosted on **Greenhouse** and **Lever**, applications can be submitted programmatically without proprietary partner credentials. However:
1. **Diverse & Dynamic Question Schemas**: Every employer configures unique required screening questions (e.g. legal authorization, visa sponsorship, years of experience, custom checkboxes, and open-ended essays).
2. **Bot Challenges & Captchas**: Certain employers activate reCAPTCHA or Cloudflare Turnstile on their public boards, which cannot be solved in headless backend execution.
3. **Data Integrity & Risk of Disqualification**: Blindly submitting fabricated or guessed answers to unmapped questions leads to immediate applicant disqualification.

### 1.2 User Value
- **Job Seeker**: Routine applications with standard screening questions are submitted automatically and accurately using their profile and authentic CV without manual form typing.
- **Worker / System**: Safely determines whether an application can be automated (100% question confidence + no bot challenge) or must pause for human review (`needs_review`) or manual submission (`manual_apply`).
- **Safety & Transparency**: Protects candidate reputation by guaranteeing that open-ended essays or ambiguous questions are never blindly submitted.

---

## 2. Scope & Boundaries

### 2.1 In Scope
1. **Base Submitter Interface (`jobs/apply/base.py`)**:
   - Data models: `ScreeningQuestion`, `QuestionOption`, `SubmissionResult`, `SubmitResponse`, and result statuses (`ready`, `needs_review`, `manual_apply`, `submitted`, `error`).
   - Abstract `BaseSubmitter` contract:
     - `fetch_questions(posting: JobPosting) -> list[ScreeningQuestion]`
     - `map_and_validate_payload(user: User, posting: JobPosting, questions: list[ScreeningQuestion]) -> SubmissionResult`
     - `submit(user: User, posting: JobPosting, payload: dict, resume_stream: io.BytesIO, filename: str, content_type: str) -> SubmitResponse`
   - Common question classification utilities (fuzzy/regex matching for standard fields).

2. **Greenhouse Submitter (`jobs/apply/greenhouse.py`)**:
   - Public Boards API v1 integration:
     - Schema fetch: `GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{id}?questions=true`.
     - Multipart dispatch: `POST https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{id}`.
   - Mapping standard applicant fields: `first_name`, `last_name`, `email`, `phone`, `resume` (PDF stream), `mapped_url_token`.
   - Mapping dynamic screening questions (`question_{id}`, `question_{id}[]`) against `user.screening_defaults` and `user.resume_data`.
   - Handling Greenhouse field types: `input_text`, `textarea`, `multi_value_single_select`, `multi_value_multi_select`, `input_file`.
   - Captcha detection (`g-recaptcha-response`, `recaptcha_response`, or HTTP 400/422 with captcha error) -> routes to `manual_apply` with `reason="captcha_blocked"`.

3. **Lever Submitter (`jobs/apply/lever.py`)**:
   - Public Postings API v0 integration:
     - Schema fetch: `GET https://api.lever.co/v0/postings/{company}/{id}?mode=json`.
     - Multipart dispatch: `POST https://api.lever.co/v0/postings/{company}/{id}`.
   - Mapping standard applicant fields: `name` (full name), `email`, `phone`, `org`, URLs (`urls[LinkedIn]`, `urls[GitHub]`, `urls[Portfolio]`, `urls[Twitter]`, `urls[Other]`), `comments`, `resume` (file field).
   - Mapping custom card fields (`cards[{card_id}][{field_id}]`) and consent checkboxes (`consent[marketing]`, `consent[data-retention]`).
   - Captcha detection (`g-recaptcha-response`, `h-captcha-response`, or HTTP 400 with captcha error) -> routes to `manual_apply` with `reason="captcha_blocked"`.

4. **Safety Decision Gate & State Machine**:
   - `100% Mapped` (all required fields confidently resolved, no captcha) -> `SubmissionResult.status = "ready"`.
   - `Unmapped / Ambiguous / Essay` (any required field unresolved or textarea > 100 chars) -> `SubmissionResult.status = "needs_review"`.
   - `Bot Challenge Detected` -> `SubmitResponse.status = "manual_apply"`.
   - `Closed / Missing Job (HTTP 404)` -> `SubmitResponse.status = "stale_closed"`.

5. **In-Memory Resume Lifecycle Integration**:
   - Directly consumes `download_resume_stream(user.resume_storage_path)` in memory (`io.BytesIO`). Zero disk writes.

6. **Inspection & Dry-Run Mode**:
   - Standalone CLI/function capability (`--dry-run-apply` or `dry_run=True`) allowing inspection of ATS question schemas and simulation of mapping decisions without triggering HTTP POST.

### 2.2 Out of Scope (Ponytail Pushback / The "Never Written" Code)
- **Direct Submission to Ashby, SmartRecruiters, Teamtailor, Workday**: Dropped from automation per Spike #49. Ashby enforces mandatory Cloudflare Turnstile; SmartRecruiters and Teamtailor require authenticated employer API keys. All automatically resolve to `manual_apply`.
- **Captcha Solving & Bypass Services**: Dropped. No headless browser emulation, no 2Captcha/anti-captcha API integrations. If captcha is present, immediately yield to `manual_apply`.
- **LLM Synthesis for Open-Ended Questions**: Deferred to Issue #59. Issue #51 strictly classifies open-ended questions and marks them for human review (`needs_review`).
- **Database Queue Consumer / Worker Daemon**: Deferred to Issue #52. Issue #51 provides the pure submitter engines, question fetchers, and validators.
- **ReportLab PDF Generation**: Permanently rejected per Issue #63 and Constitution §1.2. Only authentic uploaded candidate CVs are streamed.

---

## 3. Functional Requirements

### 3.1 Domain Models (`jobs/apply/base.py`)

#### 3.1.1 `QuestionType` (Enum / Literal)
```python
class QuestionType(str, Enum):
    SHORT_TEXT = "short_text"  # Single-line string input
    LONG_TEXT = "long_text"  # Multiline / essay textarea
    SINGLE_SELECT = "single_select"  # Dropdown / radio options
    MULTI_SELECT = "multi_select"  # Multiple choice checkboxes
    FILE = "file"  # File attachment (other than primary resume)
    BOOLEAN = "boolean"  # Single checkbox / Yes-No toggle
```

#### 3.1.2 `ScreeningQuestion`
```python
@dataclass
class QuestionOption:
    id: str | int
    label: str


@dataclass
class ScreeningQuestion:
    id: str | int
    label: str
    question_type: QuestionType
    required: bool
    options: list[QuestionOption] = field(default_factory=list)
    raw_field_name: str | None = None
    description: str | None = None
```

#### 3.1.3 `SubmissionResult` & `SubmitResponse`
```python
@dataclass
class SubmissionResult:
    status: Literal["ready", "needs_review", "manual_apply"]
    payload: dict[str, Any] = field(default_factory=dict)
    unmapped_questions: list[ScreeningQuestion] = field(default_factory=list)
    reason: str | None = None


@dataclass
class SubmitResponse:
    status: Literal["submitted", "needs_review", "manual_apply", "stale_closed", "failed"]
    external_application_id: str | None = None
    redirect_url: str | None = None
    reason: str | None = None
    http_status: int | None = None
    error_message: str | None = None
```

### 3.2 Screening Question Mapping Engine

The mapping engine matches questions against candidate profile fields and `user.screening_defaults`:

1. **Work Authorization**:
   - Matches question labels containing: `legally authorized`, `work authorization`, `eligible to work`, `right to work`.
   - Evaluates `user.screening_defaults.get("work_authorization")` (boolean).
   - Maps to target boolean or select option (`"Yes"` / `"No"`).

2. **Visa Sponsorship**:
   - Matches question labels containing: `sponsorship`, `require visa`, `h-1b`, `visa status`.
   - Evaluates `user.screening_defaults.get("requires_sponsorship")` (boolean).
   - Maps to target boolean or select option (`"Yes"` / `"No"`).

3. **Years of Experience**:
   - Matches question labels containing: `years of experience`, `how many years`, `experience in years`.
   - Evaluates `user.screening_defaults.get("years_experience")` (integer).
   - Maps to numeric text or matches select option range (e.g. `"1-3 years"`, `"3-5 years"`).

4. **Notice Period**:
   - Matches question labels containing: `notice period`, `how soon can you start`, `availability`.
   - Evaluates `user.screening_defaults.get("notice_period_days")` (integer).
   - Maps to text (e.g. `"30 days"`, `"Immediately"`) or corresponding option.

5. **Location / Current Residence**:
   - Matches question labels containing: `current location`, `where are you based`, `city and country`.
   - Evaluates candidate location from `user.resume_data.get("location")` or `user.screening_defaults.get("location")`.

6. **Candidate Social & Portfolio URLs**:
   - Matches labels for `LinkedIn`, `GitHub`, `Portfolio`, `Website`, `Twitter`.
   - Evaluates `user.resume_data.get("urls")` or `user.resume_data.get("linkedin")`, etc.

7. **Open-Ended / Essay Questions**:
   - Any required question with `question_type == QuestionType.LONG_TEXT` or label matching essay queries (e.g. *"Why do you want to work here?"*, *"Describe a project"*) CANNOT be answered by scalar defaults.
   - Result: Added to `unmapped_questions` -> triggers `needs_review`.

### 3.3 Greenhouse Submitter Specification (`jobs/apply/greenhouse.py`)

#### 3.3.1 Question Fetching
- **URL**: `GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job_id}?questions=true`
- **Parsing**:
  - Traverses the `questions` array.
  - Inspects `fields` inside each question to determine `name`, `type`, `values`, and `required`.
  - Identifies captcha fields: If any field matches `recaptcha` or `g-recaptcha-response`, flags board as requiring captcha.

#### 3.3.2 Payload Preparation
- Splits user's full name into `first_name` and `last_name`.
- Maps standard fields:
  - `first_name`: string
  - `last_name`: string
  - `email`: string
  - `phone`: string
  - `mapped_url_token`: Greenhouse board token
- Maps custom questions:
  - Single-line / textarea: `question_{id} = answer_value`
  - Multi-select: `question_{id}[] = [val1, val2]`
  - Dropdowns: matches option value or option id.

#### 3.3.3 Submission Dispatch
- **URL**: `POST https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job_id}`
- Formats payload as `multipart/form-data`:
  - `data`: form fields mapped above.
  - `files`: `{"resume": (filename, resume_stream.getvalue(), content_type)}`.
- **Response Handling**:
  - `200 OK` / `201 Created`: Returns `SubmitResponse(status="submitted", external_application_id=...)`.
  - `400 Bad Request` / `422 Unprocessable Entity`:
    - If error text contains `"captcha"`, `"recaptcha"`, or `"robot"`: Returns `SubmitResponse(status="manual_apply", reason="captcha_blocked")`.
    - Otherwise: Returns `SubmitResponse(status="needs_review", error_message=...)`.
  - `404 Not Found`: Returns `SubmitResponse(status="stale_closed", reason="job_closed")`.
  - `429 Too Many Requests` / `5xx`: Raises transient retry error or returns `SubmitResponse(status="failed", reason="rate_limited")`.

### 3.4 Lever Submitter Specification (`jobs/apply/lever.py`)

#### 3.4.1 Question Fetching
- **URL**: `GET https://api.lever.co/v0/postings/{company}/{job_id}?mode=json`
- **Parsing**:
  - Extracts standard fields (`name`, `email`, `phone`, `org`, `urls`, `comments`).
  - Extracts custom questions from `cards` array:
    - Card ID, field ID, title, `type` (`text`, `textarea`, `dropdown`, `yes-no`, `multiple-choice`), `required`.
  - Identifies consent fields (`consent[marketing]`, `consent[data-retention]`).

#### 3.4.2 Payload Preparation
- Sets standard fields:
  - `name`: user's full name.
  - `email`: user's email.
  - `phone`: user's phone.
  - `urls[LinkedIn]`, `urls[GitHub]`, `urls[Portfolio]`: candidate profile links.
  - `comments`: optional cover letter or introduction.
- Maps card fields:
  - `cards[{card_id}][{field_id}]`: mapped answer string.
- Maps consent fields:
  - `consent[data-retention]`: `"true"` (required for GDPR compliance).

#### 3.4.3 Submission Dispatch
- **URL**: `POST https://api.lever.co/v0/postings/{company}/{job_id}`
- Formats payload as `multipart/form-data`:
  - `data`: form fields mapped above.
  - `files`: `{"resume": (filename, resume_stream.getvalue(), content_type)}`.
- **Response Handling**:
  - `200 OK` (`{"ok": true, ...}`): Returns `SubmitResponse(status="submitted", external_application_id=...)`.
  - `400 Bad Request`:
    - If error text contains `"captcha"` or `"robot"`: Returns `SubmitResponse(status="manual_apply", reason="captcha_blocked")`.
    - Otherwise: Returns `SubmitResponse(status="needs_review", error_message=...)`.
  - `404 Not Found`: Returns `SubmitResponse(status="stale_closed", reason="posting_closed")`.
  - `429 Too Many Requests` / `5xx`: Returns `SubmitResponse(status="failed", reason="server_error")`.

### 3.5 In-Memory Resume Handling
- Submitter never writes files to `/tmp` or disk.
- Accepts `resume_stream: io.BytesIO` (originating from `cv_storage.download_resume_stream`).
- Multipart file tuple passed to `httpx.AsyncClient(..., files={"resume": (filename, stream.getvalue(), content_type)})`.

### 3.6 Dry-Run and Inspection Mode
- `inspect_posting_questions(posting: JobPosting) -> list[ScreeningQuestion]`:
  Fetches question schema without mapping or submitting.
- `preview_submission(user: User, posting: JobPosting) -> SubmissionResult`:
  Fetches schema, executes mapping, and returns formatted multipart payload and decision status (`ready`, `needs_review`, `manual_apply`) without dispatching HTTP POST.

---

## 4. Constitution & Invariant Checks

- [x] **Respects database pooler requirements (Constitution §1.1)**:
  - Submitters do not hold database connections open. Question schema fetch and HTTP POST dispatch run purely in-memory using `httpx.AsyncClient`.
- [x] **Respects zero-disk file storage (Constitution §1.2)**:
  - Direct multipart streaming from `io.BytesIO`. Zero disk writes in `/tmp` or workspace.
- [x] **Respects scraper/API rate limits & concurrency pools (Constitution §1.4)**:
  - Leverages standard 30-worker semaphore for Greenhouse and Lever endpoints.
  - Cleanly handles HTTP 429 backoff responses.
- [x] **Respects ATS submission safety gate (Constitution §1.5)**:
  - Submissions executed ONLY when 100% of required questions are mapped and no captcha is active.
  - All non-Greenhouse/Lever platforms, or captcha-blocked boards, cleanly routed to `manual_apply`.
  - Unmapped or open-ended essay questions safely routed to `needs_review`.

---

## 5. Acceptance Criteria

### 5.1 Unit Tests & Test Coverage
1. **Base Submitter & Types**:
   - `test_question_mapping_deterministic`: Verifies work authorization, visa sponsorship, years of experience, and notice period mapping.
   - `test_question_mapping_unmapped_and_essays`: Verifies that open-ended textareas or unfamiliar required questions produce `needs_review`.
2. **Greenhouse Submitter**:
   - `test_greenhouse_fetch_questions`: Correctly parses standard and custom questions from mock Greenhouse JSON.
   - `test_greenhouse_submit_success`: Successful submission with 100% mapped questions, validating multipart form fields and resume stream.
   - `test_greenhouse_captcha_fallback`: Mock 400/422 response with captcha error transitions to `manual_apply` with `reason="captcha_blocked"`.
   - `test_greenhouse_404_closed`: Mock 404 response transitions to `stale_closed`.
3. **Lever Submitter**:
   - `test_lever_fetch_questions`: Correctly parses cards, custom fields, and consent requirements from mock Lever JSON.
   - `test_lever_submit_success`: Successful submission with full card field mapping and resume stream.
   - `test_lever_captcha_fallback`: Captcha response transitions to `manual_apply`.
   - `test_lever_404_closed`: Mock 404 response transitions to `stale_closed`.
4. **Dry-Run & Inspection**:
   - `test_dry_run_preview`: Validates that `preview_submission` returns payload and status without making POST calls.

### 5.2 Verification Standards
- Zero external network calls in unit tests (`httpx.MockTransport`).
- `ruff check .` with zero errors.
- `ruff format --check .` passing.
- `mypy` passing on all new apply modules.
