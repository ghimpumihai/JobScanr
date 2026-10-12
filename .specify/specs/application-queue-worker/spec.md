# Feature Specification: Resilient Application Queue Worker with Domain Throttling and Crash Recovery

**Feature Slug**: `application-queue-worker`  
**Status**: Converged (2026-10-12)  
**Issue Reference**: Fixes #53 (Backend / Worker Stream)  
**Dependencies**: Issue #45 (DB Schema), Issue #51 (Submitters), Issue #63 (In-Memory CV Storage)  
**Created**: 2026-10-12  

---

## 1. Problem Statement & User Value

### 1.1 Problem Statement
When background workers submit automated job applications across multiple users and company ATS boards, several systemic failure modes emerge if the queue worker is unconstrained:
1. **Connection Pool Starvation**: Workers holding database transactions or row-level locks open across slow external HTTP requests (e.g. ATS multipart uploads or slow responses) exhaust the database connection pool (`psycopg_pool.ConnectionPool`), causing timeouts across all worker and API threads.
2. **ATS Domain Flooding & IP Bans**: Blasting multiple applications concurrently to the same company ATS board triggers rate limiting (HTTP 429), bot suspicion, or IP bans, jeopardizing candidate applications.
3. **In-Memory Rate Limit Volatility**: Tracking daily submission quotas (`max_daily_applications`) or per-company limits (`max_apps_per_company`) in volatile in-memory process state fails during multi-worker deployments, restarts, or crashes, causing over-submission.
4. **Zombie Locks on Worker Crashes**: If a worker process abruptly terminates (SIGKILL, container preemption, OOM) while executing an HTTP submission, claimed rows remain permanently trapped in `status = 'submitting'` without automated detection or recovery.
5. **Ghost Submissions on Retries**: Blindly re-submitting timed-out or unconfirmed application attempts risks submitting duplicate applications for the same candidate to the same ATS posting.

### 1.2 User Value
- **Job Seekers**: Applications are reliably submitted without duplicates, respecting candidate-configured daily limits and per-company caps across all worker instances.
- **System Stability**: The database connection pool remains healthy because DB connections are released immediately upon claiming rows, never held during HTTP calls or throttling delays.
- **Platform Hygiene**: Pacing delays (30–60s) between submissions to the same company ATS board protect IP reputation and prevent 429 throttling.
- **Zero Orphaned Applications**: Crashed or stalled submissions are automatically identified by a recovery reaper and transitioned to `needs_review` with clear audit trails in `application_events`.

---

## 2. Scope & Boundaries

### 2.1 In Scope
- **PostgreSQL Queue Polling Engine (`jobs/apply/runner.py`)**:
  - `SELECT ... FOR UPDATE SKIP LOCKED` on `applications` to claim available jobs.
  - Generates unique UUID `attempt_token` and updates `status = 'submitting'`, `locked_at = NOW()`, incrementing `attempts = attempts + 1`.
  - Transaction commits and releases the database pool connection immediately upon claim.
- **Cross-User Domain Throttling without Pool Starvation**:
  - Candidate queue selection query excludes rows where the target company ATS board has had an active lock or submission within the last 60 seconds across ALL users:
    ```sql
    AND NOT EXISTS (
        SELECT 1 FROM applications active_apps
        JOIN job_postings active_jp ON active_apps.job_posting_id = active_jp.id
        WHERE active_jp.company_id = jp.company_id
          AND active_apps.locked_at > NOW() - INTERVAL '60 seconds'
    )
    ```
  - Zero idle connection sleeps: The worker never holds a connection while waiting for domain pacing windows.
- **Persistent DB-Enforced Application Quotas**:
  - Daily cap check: Verifies submissions in the current day (`CURRENT_DATE`) for `user_id` against `users.max_daily_applications` (default 10) directly from database state (`applications` and `application_events`).
  - Per-company cap check: Verifies existing submissions for `(user_id, company_id)` against `users.max_apps_per_company` (default 2) directly from database state.
  - Rows exceeding limits are gracefully skipped or marked with appropriate audit reasons.
- **Pre-Submission Liveness Gate**:
  - Performs an HTTP HEAD/GET check against `job_postings.url` immediately before building the submission payload.
  - If the posting returns HTTP 404 or redirects to a closed board, updates status to `stale_closed` and logs event in `application_events` without attempting submission.
- **Crash Recovery Reaper (`reap_stuck_applications`)**:
  - Periodic scan for applications stuck in `status = 'submitting'` with `locked_at < NOW() - INTERVAL '5 minutes'`.
  - Transitions ambiguous abandoned rows to `status = 'needs_review'` with `reason = 'worker_timeout_unconfirmed'` rather than blindly retrying, preventing duplicate applicant records in the ATS.
- **Immutable Audit Trail (`application_events`)**:
  - Logs every state transition: `queued -> submitting`, `submitting -> submitted`, `submitting -> needs_review`, `submitting -> manual_apply`, `submitting -> failed`, and `submitting -> stale_closed`.

### 2.2 Out of Scope (Ponytail Pushback / The "Never Written" Code)
- **Separate Celery / Redis Queue Broker**: No Redis, RabbitMQ, or Celery dependencies. PostgreSQL `FOR UPDATE SKIP LOCKED` natively provides resilient distributed locking without additional operational infrastructure.
- **In-Memory Rate Limiting Redis Caches**: Dropped in favor of atomic SQL queries on `applications`.
- **Complex Distributed Lock Managers (e.g. Redlock, etcd)**: Not needed; PostgreSQL row locks and timestamp predicate filtering provide transactional guarantees.
- **Direct Submission on Unsupported Platforms**: Non-Greenhouse / non-Lever platforms route directly to `manual_apply` per Constitution §1.5.

---

## 3. User Stories & Acceptance Criteria

### 3.1 User Stories
- **US-1**: As a candidate, I want my queued applications to be dispatched sequentially to ATS platforms without holding database connections open during network calls so that the application system is resilient to network delays.
- **US-2**: As a candidate, I want the system to ensure at most my configured daily limit of jobs (e.g. 10) and per-company limit (e.g. 2) are submitted each day, even if background workers crash and restart.
- **US-3**: As an operator, I want automated submissions to the same company board to be spaced by at least 60 seconds across all candidates to prevent ATS 429 rate limiting and bot detection.
- **US-4**: As an operator, I want worker crashes or container restarts to automatically release or flag abandoned submissions without double-submitting to the ATS.

### 3.2 Acceptance Criteria
1. **Zero Connection Pool Starvation**:
   - The database transaction claiming a queued application releases its connection back to `get_pool()` before initiating any HTTP call (liveness check, ATS question schema fetch, or multipart submission).
2. **Domain Throttling Enforcement**:
   - Consecutive applications targeting the same `company_id` are never claimed concurrently or within 60 seconds of each other.
   - If multiple candidates have queued applications for company A, worker A claims candidate 1's job, while company A's second job remains queued until 60 seconds have elapsed since candidate 1's `locked_at`.
3. **Persistent Quotas**:
   - If user U has already submitted 10 applications today, any further queued jobs for user U are not claimed for submission, or transitioned with quota reason.
   - If user U has already submitted 2 applications to company C, any further queued jobs for user U at company C are prevented.
4. **Liveness Validation**:
   - Target job URL returning 404 immediately transitions the application to `status = 'stale_closed'` and records an event in `application_events`. No submission is sent to ATS.
5. **Crash Recovery Reaper**:
   - Running `reap_stuck_applications()` claims rows with `status = 'submitting'` and `locked_at < NOW() - INTERVAL '5 minutes'`.
   - Transitions those rows to `status = 'needs_review'` with `reason = 'worker_timeout_unconfirmed'`, logging the event in `application_events`.
   - No rows remain permanently stuck in `submitting`.

---

## 4. Constitution & Invariant Alignment

This specification strictly aligns with `.specify/constitution.md`:
- **§1.1 Database Pooler & Network Constraints**: Mandatory session pooler usage; connection pool connections must NEVER be held open during long-running HTTP operations or worker sleeps.
- **§1.2 Zero Temporary Disk Storage**: Authentic candidate resumes streamed directly in-memory via `cv_storage.download_resume_stream`.
- **§1.5 ATS Application Submission Safety Gate**: Submitter execution respects screening question completeness and captcha fallback.

---

## 5. Failure Modes & Edge Cases

| Failure Mode | Root Cause | System Response / Safeguard |
| :--- | :--- | :--- |
| **Worker killed mid-HTTP post** | SIGKILL / OOM during upload | Row remains in `submitting`. Reaper detects `locked_at > 5 min` and moves to `needs_review` (`worker_timeout_unconfirmed`). |
| **ATS endpoint slow / hangs** | ATS server lag (e.g. 30s response) | Worker HTTP timeout (30s). DB connection was already released before HTTP call; pool is unaffected. |
| **Company ATS returns 404** | Job closed since discovery | Liveness gate checks URL prior to form submission, marks `stale_closed`. |
| **All jobs belong to one company** | Batch of jobs from single company | Queue query filters out jobs for company if locked within 60s. Worker sleeps/idles cleanly without holding DB connections. |
| **User daily quota exhausted** | User reached `max_daily_applications` | SQL filter counts today's submissions for `user_id` and excludes or halts candidate processing. |
