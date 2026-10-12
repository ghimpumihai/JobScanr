# Technical Implementation Plan: Resilient Application Queue Worker with Domain Throttling and Crash Recovery

**Feature Slug**: `application-queue-worker`  
**Spec Reference**: [.specify/specs/application-queue-worker/spec.md](./spec.md)  
**Status**: Converged (2026-10-12)  
**Created**: 2026-10-12  

---

## 1. Architectural Strategy & Design Trade-offs

### 1.1 Summary of Technical Approach
Implement a resilient, stateless application queue worker in `jobs/apply/runner.py` that drains queued jobs from PostgreSQL without connection pool starvation or domain flooding:
1. **Immediate Connection Release**: The atomic queue claim operation uses `SELECT ... FOR UPDATE OF a SKIP LOCKED` on the `applications` table to claim a single application, sets `status = 'submitting'`, `attempt_token = gen_random_uuid()`, `locked_at = NOW()`, increments `attempts`, and records an audit event in `application_events`. The database transaction commits and returns the connection to `psycopg_pool.ConnectionPool` **immediately** before any HTTP network calls take place.
2. **Domain Throttling Without Idle Sleep Locks**: Rather than holding row locks or database connections open while sleeping between submissions, domain pacing (60s) is enforced directly within the PostgreSQL query:
   ```sql
   AND NOT EXISTS (
       SELECT 1 FROM applications active_apps
       JOIN job_postings active_jp ON active_apps.job_posting_id = active_jp.id
       WHERE active_jp.company_id = jp.company_id
         AND active_apps.locked_at > NOW() - INTERVAL '60 seconds'
   )
   ```
   If all queued applications belong to throttled companies, the worker yields its DB connection and sleeps cleanly before polling again.
3. **Database-Backed Persistent Caps**: Daily submission quotas (`users.max_daily_applications`, default 10) and per-company quotas (`users.max_apps_per_company`, default 2) are calculated directly against database state (`applications` joined with `job_postings`). Worker restarts or multi-process deployments cannot bypass or desynchronize these limits.
4. **Pre-Submission Liveness Gate**: Performs an asynchronous HTTP `HEAD` or `GET` request to verify that the job posting URL is live before downloading candidate CVs or generating payloads. A 404 or inactive posting transitions the row to `stale_closed` with zero submission attempts.
5. **Crash Recovery Reaper (`reap_stuck_applications`)**: Scans for applications abandoned in `status = 'submitting'` with `locked_at < NOW() - INTERVAL '5 minutes'`. Transitions these rows to `status = 'needs_review'` with `reason = 'worker_timeout_unconfirmed'` to prevent accidental duplicate submissions while surfacing the failure to the candidate.
6. **Zero Disk In-Memory Pipeline**: Retrieves stored candidate CVs via `cv_storage.download_resume_stream` into an in-memory `io.BytesIO` buffer, passing the stream directly to `BaseSubmitter.submit()`.

### 1.2 Comparison of Alternatives Considered
| Approach | Pros | Cons | Reason for Chosen Pattern |
| :--- | :--- | :--- | :--- |
| **External Broker (Celery / Redis)** | Dedicated task queue mechanics | Adds 2 external services; requires separate operational monitoring; doesn't eliminate DB sync needs | **Rejected**: PostgreSQL `SKIP LOCKED` natively provides distributed, transactional locking without extra infrastructure. |
| **In-Memory Rate Limiting Dicts** | Trivial implementation | Resets on worker crash/restart; fails in multi-worker or containerized setups | **Rejected**: Database queries guarantee cross-process, restart-safe limit enforcement. |
| **Worker Sleeping Inside DB Transaction** | Simple sequential flow | Holds DB connection pool slot during sleep; starves connection pool under high traffic | **Rejected**: Strictly prohibited by Constitution §1.1. SQL-based throttling releases connection immediately. |
| **Auto-Retry on Stalled Submissions** | Automatic recovery | If previous submission actually reached ATS before worker crashed, retrying creates duplicate applications | **Rejected**: Conservative safety gate moves timed-out rows to `needs_review` with audit trail. |

---

## 2. Component Boundaries & Critical Files

### 2.1 Files Created
- `jobs/apply/runner.py`:
  - `claim_next_application(conn)`: Atomic SQL claim with domain throttling and quota filters.
  - `check_posting_liveness(url, client)`: Async HTTP check detecting 404/closed postings.
  - `process_application(app_claim, dry_run=False)`: End-to-end processing pipeline (liveness check -> CV retrieval -> submitter dispatch -> state update).
  - `reap_stuck_applications(timeout_minutes=5)`: Crash recovery reaper releasing abandoned rows.
  - `run_queue_worker(poll_interval=5.0, dry_run=False, max_iterations=None)`: Main worker loop with graceful termination handling (`SIGINT`, `SIGTERM`).
- `tests/test_apply_runner.py`:
  - Comprehensive unit test suite using `httpx.MockTransport` and transactional database mocks.

### 2.2 Files Modified
- `db/queries.py`:
  - Add `claim_next_queued_application()`: Encapsulated atomic claim query with domain pacing and quota checks.
  - Add `transition_application_status(app_id, to_status, from_status=None, reason=None, submitted_payload=None, next_attempt_at=None)`: Centralized state machine updater writing to both `applications` and `application_events`.
  - Add `reap_stalled_applications(stalled_threshold_seconds=300)`: Batch reaper for timed-out `submitting` rows.
- `jobs/apply/__init__.py`:
  - Export `run_queue_worker`, `reap_stuck_applications`, `process_application`, and `claim_next_application`.

---

## 3. Data Flow & Interfaces

### 3.1 Visual Architecture & Lifecycle Flow

```text
                               ┌───────────────────────────┐
                               │  Queued Applications Table │
                               └─────────────┬─────────────┘
                                             │
                       claim_next_queued_application()
                       [SELECT ... FOR UPDATE OF a SKIP LOCKED]
                       • Filter: locked_at > 60s ago for company
                       • Filter: user daily & company caps respected
                       • Atomic Update: status = 'submitting', locked_at = NOW()
                       • Transaction COMMITS & releases connection
                                             │
                                             ▼
                       ┌───────────────────────────────────────────┐
                       │   Application Claim (Detached In-Memory)   │
                       └─────────────────────┬─────────────────────┘
                                             │
                                             ▼
                               ┌───────────────────────────┐
                               │    HTTP Liveness Check    │
                               │   (HEAD / GET posting.url)│
                               └───────┬───────────┬───────┘
                                       │           │
                          HTTP 404/410 │           │ 200 OK
                                       ▼           ▼
                      ┌──────────────────────┐   ┌───────────────────────────┐
                      │ status: stale_closed │   │ Download Resume Stream    │
                      └──────────────────────┘   │ (cv_storage: In-Memory)   │
                                                 └─────────────┬─────────────┘
                                                               │
                                                               ▼
                                                 ┌───────────────────────────┐
                                                 │ Dispatch Submitter        │
                                                 │ (jobs/apply/get_submitter)│
                                                 └─────────────┬─────────────┘
                                                               │
                     ┌─────────────────────────────────────────┼────────────────────────────────────────┐
                     │                                         │                                        │
                     ▼                                         ▼                                        ▼
         [Screening Unmapped / Essay]               [CAPTCHA / Unsupported]                         [Success]
                     │                                         │                                        │
                     ▼                                         ▼                                        ▼
          status: needs_review                       status: manual_apply                       status: submitted
          (custom_answers staged)                   (candidate prefill link)                 (confirmation saved)
                     │                                         │                                        │
                     └─────────────────────────────────────────┼────────────────────────────────────────┘
                                                               │
                                                               ▼
                                                 ┌───────────────────────────┐
                                                 │ Update Status & Log Event │
                                                 │ (db/queries.py)           │
                                                 └───────────────────────────┘
```

### 3.2 Key Data Structures (`jobs/apply/runner.py`)

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
import uuid


@dataclass
class ApplicationClaim:
    id: int
    user_id: int
    job_posting_id: int
    company_id: int
    company_name: str
    ats_platform: str
    ats_identifier: str
    job_url: str
    job_title: str
    attempt_token: uuid.UUID
    attempts: int
    screening_defaults: dict[str, Any]
    resume_data: dict[str, Any]
    resume_storage_path: str | None
    resume_filename: str | None
    resume_content_type: str | None


@dataclass
class ProcessingResult:
    application_id: int
    final_status: Literal["submitted", "needs_review", "manual_apply", "stale_closed", "failed"]
    reason: str | None = None
    confirmation_id: str | None = None
    submitted_payload: dict[str, Any] | None = None
```

### 3.3 Core Database Function Signatures (`db/queries.py`)

```python
def claim_next_queued_application(
    domain_throttle_seconds: int = 60,
) -> ApplicationClaim | None:
    """Atomically claims one queued application adhering to domain throttling and user caps.

    Releases connection immediately upon committing status = 'submitting'.
    """
    ...


def transition_application_status(
    application_id: int,
    to_status: str,
    from_status: str | None = None,
    reason: str | None = None,
    submitted_payload: dict | None = None,
    next_attempt_at: datetime | None = None,
) -> bool:
    """Updates application status and writes an immutable audit record to application_events."""
    ...


def reap_stalled_applications(stalled_threshold_seconds: int = 300) -> int:
    """Reaps applications stuck in 'submitting' beyond the timeout threshold,
    moving them to 'needs_review' with reason 'worker_timeout_unconfirmed'.
    """
    ...
```

---

## 4. Testing & Verification Strategy

### 4.1 Mocking Strategy
- **Database Mocks**: Use `unittest.mock.MagicMock` wrapping `get_connection()` to verify SQL syntax, transaction commits, and parameter binding without requiring live PostgreSQL database instances.
- **HTTP Client Mocks**: Use `httpx.MockTransport` and `respx` to mock ATS responses, liveness 404 responses, network timeouts, and multipart uploads.
- **CV Storage Mocks**: Mock `download_resume_stream` returning `io.BytesIO(b"%PDF-1.4 mock resume content")`.

### 4.2 Test Scenarios in `tests/test_apply_runner.py`
1. **Atomic Claim & Connection Release**: Verify `claim_next_queued_application` executes within a discrete connection context and returns an `ApplicationClaim`.
2. **Domain Throttling Enforcement**: Verify query parameters and filtering ensure jobs from the same company are not claimed if `locked_at` was within the throttle window.
3. **Daily and Per-Company Quota Caps**: Verify jobs exceeding user `max_daily_applications` or `max_apps_per_company` are excluded by the query.
4. **Liveness Gate 404 Transition**: Mock posting URL returning 404; assert application transitions directly to `stale_closed` without attempting ATS submission.
5. **Successful Greenhouse & Lever Processing**: Mock valid question schema and successful submission; assert transition to `submitted` with payload confirmation.
6. **Captcha & Unmapped Questions**: Verify appropriate fallback to `manual_apply` and `needs_review`.
7. **Crash Recovery Reaper**: Seed stalled `submitting` rows with `locked_at` older than 5 minutes; assert reaper transitions them to `needs_review` and creates audit event entries.
8. **Worker Loop Graceful Exit**: Verify `run_queue_worker` exits cleanly upon signal or `max_iterations`.

### 4.3 Verification Commands
```bash
ruff check .
ruff format --check .
mypy models.py config.py scrapers/
python -m pytest tests/test_apply_runner.py -v
```

---

## 5. Risk Assessment & Safety Circuit Breakers

| Risk / Failure Mode | Severity | Mitigation / Circuit Breaker |
| :--- | :--- | :--- |
| **Connection Pool Exhaustion** | High | Connections are strictly claimed and committed within small, isolated helper functions. Never passed into long-running async HTTP methods. |
| **Duplicate Applications on Network Drop** | High | Any unconfirmed crash or timeout is flagged as `needs_review` (`worker_timeout_unconfirmed`) rather than retried. Candidates must manually review ambiguous attempts. |
| **ATS Denial of Service / IP Ban** | High | 60-second domain throttle per company enforced at SQL layer. Worker pauses between polling sweeps when no unthrottled jobs are ready. |
| **Corrupted / Missing CV Files** | Medium | If `download_resume_stream` fails, the row transitions to `needs_review` with `reason = 'resume_file_missing'`, logging error details. |
