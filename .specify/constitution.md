# Project Constitution & Architectural Invariants

> **Repository**: JobScanr  
> **Framework Reference**: [GitHub Spec Kit](https://github.com/github/spec-kit)  
> **Status**: Living Invariants Contract  
> **Authority**: Mandatory architectural guardrails across all development, planning, and agentic workflows.

---

## 1. Core Invariants & Architectural Non-Negotiables

Every feature, plan, and pull request must strictly comply with the following invariants:

### 1.1 Database Pooler & Network Constraints
- **Session Pooler Mandatory**: The production and staging database is Supabase PostgreSQL. Direct host (`db.<ref>.supabase.co`) is IPv6-only. All connections must use the AWS Session Pooler (`aws-0-*.pooler.supabase.com:5432`) to prevent connection timeouts in IPv4-only and container environments.
- **Connection Release During Long Operations**: Database connection pool connections must NEVER be held open during long-running HTTP operations, external API calls, or worker backoff sleeps (`SELECT ... FOR UPDATE SKIP LOCKED` transactions must release immediately after claiming a row).

### 1.2 In-Memory PDF Lifecycle (Zero-Disk Storage)
- **Zero Temporary Disk Writes**: Tailored resumes compiled via ReportLab (`jobs/apply/pdf_generator.py`) must be created directly in memory (`io.BytesIO`).
- **Direct Multipart Streaming**: File uploads to ATS endpoints or storage streams must read directly from the in-memory buffer. Temporary files on disk (`/tmp`, workspace root) are prohibited to ensure stateless execution and data privacy.

### 1.3 Job Description Storage
- **No Description Persistence in Database**: Job descriptions are never stored in the PostgreSQL database to conserve storage. They are inspected in-memory during scraping, matching, and enrichment.
- **Lazy Enrichment**: Detail endpoints (Ashby GraphQL, SmartRecruiters detail) are only queried lazily for candidates that pass initial title/location pre-filtering.

### 1.4 Scraper Concurrency & Rate Limiting
- **Concurrency Pools**:
  - Fast platforms (Greenhouse, Lever, SmartRecruiters, Teamtailor): 30-worker semaphore.
  - Workday: Dedicated 20-worker pool; identifiers must strictly follow `tenant|wdN|site`.
  - Ashby: Serialized pacing lock (`asyncio.Lock()` with 0.5s pause) to prevent GraphQL drops and soft-throttling null payloads.
- **Circuit Breakers**:
  - Scrape pipeline aborts if failure rate exceeds 20% (`FAILURE_RATE_LIMIT = 0.2`).
  - Company link pruning is hard-capped at 15% (`--max-remove-pct 0.15`).

### 1.5 ATS Application Submission & Human-in-the-Loop Safety Gate
- **Conditional Automated Submissions**: Backend headless HTTP submission is ONLY permitted for **Greenhouse** and **Lever** when:
  1. 100% of required screening questions are confidently mapped against `user.screening_defaults`.
  2. No CAPTCHA / bot challenge (reCAPTCHA, hCaptcha) is triggered.
- **Mandatory Manual Apply Fallback**: All other platforms (**Ashby**, **SmartRecruiters**, **Teamtailor**, **Workday**, **Google**), or any submission where CAPTCHA is encountered, must be cleanly routed to `manual_apply` with candidate prefill helpers.
- **Open-Ended Screening Questions**: Open-ended or essay questions must never be blindly submitted. LLM drafts must be staged in `applications.custom_answers` and transitioned to `needs_review` for explicit candidate review and approval.

---

## 2. Code Quality & Verification Standards

All merged code must satisfy:
1. **Linting**: `ruff check .` with zero errors or warnings.
2. **Formatting**: `ruff format --check .` (120-character line limit).
3. **Static Typing**: `mypy models.py config.py scrapers/` with zero type errors.
4. **Seed Validation**: `python -m scripts.validate_seed_schema` passing cleanly.
5. **Fast Unit Tests**: `python -m pytest tests/` passing 100% with zero regressions. Unit tests must use mock transports (`httpx.MockTransport`) and never make real external HTTP requests or live database mutations.

---

## 3. Spec-Driven Development Workflow

Features and non-trivial changes follow the phased lifecycle:
1. **Specify** (`/spec-specify`): Define requirements, user stories, and acceptance criteria in `.specify/specs/<feature-slug>/spec.md`.
2. **Plan** (`/spec-plan`): Formulate architecture, data flow, and file boundaries in `.specify/specs/<feature-slug>/plan.md`.
3. **Tasks** (`/spec-tasks`): Generate ordered, testable checklist tasks in `.specify/specs/<feature-slug>/tasks.md`.
4. **Implement** (`/spec-implement`): Execute tasks incrementally, verifying code against the spec and tests.
5. **Converge** (`/spec-converge`): Verify full test suites, linters, and type checkers to confirm convergence.
