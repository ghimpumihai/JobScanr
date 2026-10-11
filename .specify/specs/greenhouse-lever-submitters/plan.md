# Technical Implementation Plan: Greenhouse and Lever Submitters with Question Schema Mapping

**Feature Slug**: `greenhouse-lever-submitters`  
**Spec Reference**: [.specify/specs/greenhouse-lever-submitters/spec.md](./spec.md)  
**Status**: Executing  

---

## 1. Architectural Strategy & Design Trade-offs

### 1.1 Approach Summary
Implement modular, stateless ATS submitters for Greenhouse and Lever adhering to the unauthenticated submission mechanics established in Spike #49 and in-memory CV streaming from Issue #63:
1. **Base Submitter & Mapping Engine (`jobs/apply/base.py`)**: Defines standard data contracts (`ScreeningQuestion`, `QuestionOption`, `SubmissionResult`, `SubmitResponse`) and abstract base class `BaseSubmitter`. Implements deterministic question mapping heuristics against `user.screening_defaults` and `user.resume_data`.
2. **Greenhouse Submitter (`jobs/apply/greenhouse.py`)**: Interacts with Greenhouse Boards API v1 (`GET /v1/boards/{token}/jobs/{id}?questions=true` and `POST /v1/boards/{token}/jobs/{id}`). Dynamically converts question schemas to multipart fields (`question_{id}`, `first_name`, `last_name`, `email`, `phone`, `resume`).
3. **Lever Submitter (`jobs/apply/lever.py`)**: Interacts with Lever Postings API v0 (`GET /v0/postings/{company}/{id}?mode=json` and `POST /v0/postings/{company}/{id}`). Maps applicant fields and dynamic custom `cards` into multipart form parameters.
4. **Safety & Fallback Decisions**: Enforces Constitution §1.5: automated submission only proceeds when 100% of required fields are mapped and no captcha is required; otherwise gracefully transitions to `needs_review` (open-ended / unmapped) or `manual_apply` (captcha challenge).
5. **Dry-Run & Inspection Mode**: Provides inspection methods to view raw question schemas and preview multipart payloads without triggering external POST requests.

### 1.2 Design Trade-offs & Ponytail Simplification
- **Reuse Existing HTTP Client Patterns**: Leverage `httpx.AsyncClient` with standard retry/backoff, matching `scrapers/base.py`.
- **No Heavy Schema Engines**: Avoid adding bulky form-validation libraries (e.g. WTForms or Cerberus). Use standard Python `@dataclass` and regex for question label categorization.
- **Stateless & Database-Decoupled**: Submitters do not hold database connections open or write to DB tables directly. Queue management and database state transitions remain with the caller (Issue #52).
- **In-Memory Streaming**: Stream directly from `io.BytesIO` buffers provided by `cv_storage.download_resume_stream`. Zero disk operations.

---

## 2. Component Boundaries & Critical Files

### 2.1 Files Created
- `jobs/apply/base.py`: Domain dataclasses, question mapping engine, and abstract `BaseSubmitter`.
- `jobs/apply/greenhouse.py`: `GreenhouseSubmitter` implementation with schema parser, payload mapper, and HTTP dispatcher.
- `jobs/apply/lever.py`: `LeverSubmitter` implementation with card parser, consent mapper, and HTTP dispatcher.
- `tests/test_apply_submitters.py`: Unit test suite covering question fetching, mapping decisions, multipart submissions, and captcha fallbacks.

### 2.2 Files Modified
- `jobs/apply/__init__.py`: Export public submitters and helper interfaces.
- `models.py`: Optional alias/type helpers if needed.

---

## 3. Data Flow & Interfaces

```text
[User & JobPosting]
        │
        ▼
[Submitter.fetch_questions(posting)] ──> [list[ScreeningQuestion]]
        │
        ▼
[Submitter.map_and_validate_payload(user, posting, questions)]
        │
        ├──> Unmapped Required / Essay Question ──> [SubmissionResult(status="needs_review")]
        │
        └──> 100% Mapped Confidently ──> [SubmissionResult(status="ready", payload=...)]
                                                │
                                                ▼
                                   [Submitter.submit(user, posting, payload, resume_stream)]
                                                │
                                                ├──> Captcha / Bot Challenge ──> [SubmitResponse(status="manual_apply")]
                                                ├──> 200/201 Success ──────────> [SubmitResponse(status="submitted")]
                                                └──> 404 Job Closed ───────────> [SubmitResponse(status="stale_closed")]
```

### 3.1 Core Types (`jobs/apply/base.py`)
```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal
import io


class QuestionType(str, Enum):
    SHORT_TEXT = "short_text"
    LONG_TEXT = "long_text"
    SINGLE_SELECT = "single_select"
    MULTI_SELECT = "multi_select"
    FILE = "file"
    BOOLEAN = "boolean"


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

---

## 4. Testing & Verification Strategy

- **Mock Transports**: All tests utilize `httpx.MockTransport` to simulate Greenhouse and Lever API responses with zero real network traffic.
- **Test Scenarios**:
  1. *Schema Fetching*: Parsing standard fields, single-select options, multiline questions, and consent requirements.
  2. *Mapping Logic*: Mapping work authorization, visa sponsorship, years of experience, notice period, location, and URLs.
  3. *Safety Gate*: Unmapped required questions or essay textareas (>100 chars) routing to `needs_review`.
  4. *Submission Dispatch*: Validating multipart payloads, field formats (`first_name`, `last_name`, `cards[...]`), and in-memory resume attachment.
  5. *Bot Protection*: Captcha detection in responses (400/422 with captcha messages) routing to `manual_apply` with `reason="captcha_blocked"`.
  6. *Job Closure*: HTTP 404 responses routing to `stale_closed`.
  7. *Dry-Run Preview*: Verifying payload inspection without HTTP POST execution.
- **Verification Commands**:
  ```bash
  /home/stef/JobScanr/.venv/bin/ruff check .
  /home/stef/JobScanr/.venv/bin/ruff format --check .
  /home/stef/JobScanr/.venv/bin/mypy models.py config.py scrapers/
  /home/stef/JobScanr/.venv/bin/pytest tests/test_apply_submitters.py
  ```

---

## 5. Risk Assessment & Safety Circuit Breakers

1. **Transient Network Drops & ATS Outages**: Use timeout (15s) and catch `httpx.RequestError`, categorizing as `failed` with retry eligibility.
2. **Database Integrity**: Submitters are pure business logic modules with no direct DB connections, completely isolating long HTTP requests from the database connection pool.
3. **Candidate Disqualification Risk**: Absolute rule: unmapped or ambiguous required fields are NEVER guessed. If confidence < 100%, transition to `needs_review`.
