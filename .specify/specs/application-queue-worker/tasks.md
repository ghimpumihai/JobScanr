# Implementation Tasks: Resilient Application Queue Worker with Domain Throttling and Crash Recovery

**Feature Slug**: `application-queue-worker`  
**Plan Reference**: `.specify/specs/application-queue-worker/plan.md`  

---

### Task List

- [x] **Task 1: Implement Database Queue Query Functions in `db/queries.py`**
  - Implement `claim_next_queued_application(domain_throttle_seconds=60)` using `SELECT ... FOR UPDATE OF a SKIP LOCKED` on `applications`.
  - Include 60s domain throttling filter across all users.
  - Include persistent database-backed daily (`max_daily_applications`) and company (`max_apps_per_company`) quota checks.
  - Set `status = 'submitting'`, `attempt_token = gen_random_uuid()`, `locked_at = NOW()`, increment `attempts`.
  - Commit transaction and release database connection immediately upon claim.
  - Implement `transition_application_status(application_id, to_status, from_status=None, reason=None, submitted_payload=None, next_attempt_at=None)`.
  - Implement `reap_stalled_applications(stalled_threshold_seconds=300)` transitioning stuck rows to `needs_review` with reason `worker_timeout_unconfirmed`.

- [x] **Task 2: Implement Pre-Submission Liveness Gate in `jobs/apply/runner.py`**
  - Create `jobs/apply/runner.py`.
  - Implement `check_posting_liveness(url, client=None)` performing async HTTP HEAD/GET.
  - Return whether posting is active or stale/closed (HTTP 404, 410, or redirect to inactive portal).

- [x] **Task 3: Implement Application Processing Pipeline in `jobs/apply/runner.py`**
  - Implement `process_application(claim, dry_run=False, client=None)`.
  - Perform liveness check; if closed, transition to `stale_closed`.
  - Download candidate CV in-memory using `cv_storage.download_resume_stream`.
  - Dispatch to appropriate submitter via `get_submitter(claim.ats_platform)`.
  - Handle submission outcomes: `submitted` (record payload & confirmation), `needs_review` (unmapped/essay), `manual_apply` (captcha/unsupported), and `failed` with retry backoff.
  - Record audit event in `application_events` for every transition.

- [x] **Task 4: Implement Crash Recovery Reaper and Worker Polling Loop**
  - Implement `reap_stuck_applications(timeout_minutes=5)`.
  - Implement `run_queue_worker(poll_interval=5.0, dry_run=False, max_iterations=None)` with graceful signal handling (`SIGINT`, `SIGTERM`).
  - Ensure zero database connections are held during poll interval sleeps.

- [x] **Task 5: Update Package Exports in `jobs/apply/__init__.py`**
  - Export `run_queue_worker`, `process_application`, `reap_stuck_applications`, `claim_next_application`, and `ApplicationClaim`.

- [x] **Task 6: Comprehensive Unit Test Suite in `tests/test_apply_runner.py`**
  - Test atomic claim and immediate connection release with mock DB pool.
  - Test domain throttling preventing concurrent/rapid submissions to the same company board.
  - Test user daily limit and per-company limit enforcement from DB state.
  - Test 404 liveness gate transitioning to `stale_closed`.
  - Test successful submission, captcha fallback, unmapped questions, and CV streaming.
  - Test crash recovery reaper transitioning stalled rows to `needs_review`.
  - Test worker loop termination on max iterations or stop signal.

- [x] **Task 7: Verification and Lint Convergence**
  - Run `pytest tests/test_apply_runner.py`.
  - Run full test suite `pytest tests/`.
  - Run `ruff check .` and `ruff format --check .`.
  - Run `mypy models.py config.py scrapers/`.
