# Feature Specification: LLM-Drafted Answers for Open-Ended Questions in Remote Fill

**Feature Slug**: `llm-open-question-drafts`  
**Status**: Converged (2026-11-26)  
**Issue Reference**: #59 (re-scoped, see section 2; builds on #129)  
**Created**: 2026-11-26  

## 1. Problem Statement & User Value

- **Problem**: When remote fill (#129) opens an employer's Greenhouse form, it leaves every open-ended question
  ("Why do you want to work here?", "Describe a hard bug you fixed") empty and highlighted. Those questions take the
  longest to answer, and the user writes each one from scratch for every application.
- **User**: a job seeker on the remote-fill allowlist who has uploaded a CV and opted in to drafting.
- **Outcome**: when the user opens remote fill, each open-ended question already holds a short draft that uses only
  facts from the user's CV and fits the posting. The field stays highlighted. The user reads it, edits it, and
  clicks Submit themselves, the same as now.

## 2. Scope & Boundaries

Issue #59 was written for the API submitters (#51), an `applications.custom_answers` column and an "Approve &
Submit" drawer. Constitution §1.5 (2026-11-23) has since dropped automated submission, so the issue is re-scoped
onto the #129 fill plan. Decisions made on 2026-11-26:

- Drafts go into the remote-fill plan and are typed into the employer's form by remote fill.
- Drafts are grounded in text extracted from the user's uploaded CV.
- Drafting needs a per-user opt-in, because CV text and the job description go to Groq, a third party.

### In Scope
- A per-user opt-in setting, off by default, with a disclosure that CV text and the job description go to Groq.
- In-memory text extraction from the user's PDF or DOCX CV.
- A Groq drafting function with zero-hallucination prompt rules, a length cap, and retry with backoff on 429 and 5xx.
- Drafts stored on the existing fill plan's `for_user` entries, reused across plan refreshes.
- Remote fill types each draft into its own question's field and keeps the field highlighted for review.

### Out of Scope (Pushback)
- **API submitters, `custom_answers` column, approve-and-submit drawer, `needs_review` transition**: obsolete under
  constitution §1.5; the user always submits on the employer's site.
- **Lever, Ashby, other platforms**: fill plans exist only for Greenhouse (#129).
- **Showing or editing drafts inside JobScanr**: the user edits in the employer's form during remote fill.
- **Drafts for non-essay questions** (selects, checkboxes, yes/no, salary, dates, authorization, file uploads):
  these need facts, not prose; they stay with `screening_defaults` or the user.
- **Legacy `.doc` CVs and scanned (image-only) PDFs**: no text, so no drafts; the questions stay empty as today.
- **Structured `resume_data` parsing** (work history, skills JSON): drafting uses raw CV text.
- **Model fallback lists, a "redraft" button, cover letters**.

### Dependency
- #129 (remote fill spike) must be merged to `main` before implementation starts: this feature extends its fill
  plan builder, `application_fill_plans` and `fill.ts`.

## 3. Functional Requirements

### FR1: Opt-in
1. Each user has a drafting setting, off by default. The Settings page shows it with text saying the CV text and
   job description are sent to Groq to write drafts.
2. Drafts are made only for users who are on the remote-fill allowlist, have opted in, and have a CV on file.
3. When a user turns the setting off, the next plan refresh removes drafts from that user's plans. Remote fill
   types only drafts present in the plan.

### FR2: CV text extraction
1. The CV is downloaded through the existing storage helpers and read from memory only. Nothing is written to disk
   (constitution §1.2).
2. PDF and DOCX are supported. `.doc`, unreadable files and CVs with no extractable text produce no drafts; the
   reason is logged, never the CV content.
3. The CV is extracted at most once per user per pipeline run, not once per question.
4. CV text and job description are each capped in length before sending, so one request stays within Groq's
   free-tier tokens-per-minute limit.

### FR3: Drafting
1. `draft_open_question_answer(client, question_text, job_description, cv_text, max_words=150, max_chars=None)`
   returns a draft string or a failure reason. It never raises for API or network errors.
2. Only `for_user` entries with reason `open_ended` whose question is free text (long or short text) are drafted.
3. Prompt rules (from `docs/llm_question_answering_spike.md` §2.2):
   - Mention only employers, titles, tools, dates and achievements present in the CV text.
   - If the CV lacks a tool the question asks about, state the candidate's actual nearest experience honestly.
   - Never invent metrics, team sizes or money figures.
   - First person, professional, answer in the first sentence, no preamble.
4. Output is treated as untrusted plain text: trimmed, then cut at the last full sentence within `max_words`, and
   within `max_chars` when the employer's form gives a limit. An empty result counts as a failure.
5. The job description comes from the Greenhouse question response already fetched for the plan, used in memory
   and never stored (constitution §1.3).
6. Model comes from `GROQ_MODEL` with a fixed default; key from `GROQ_API_KEY`. With no key, drafting is off for
   the run and this is logged once.

### FR4: Rate limits and failures
1. On HTTP 429, 5xx, timeout or network error: retry up to 3 attempts total. Wait for `Retry-After` when given
   (capped), otherwise 2 s then 4 s.
2. Other 4xx (for example 401 bad key): no retry.
3. When attempts are exhausted, or on a non-retried error, the entry gets `draft_status: "unanswered"` with
   `draft_reason` (`rate_limit_exceeded` or `llm_error`), and drafting stops for the rest of the run (circuit
   breaker). Plan building continues without drafts; the pipeline never fails because of drafting.
4. No database connection is held during Groq calls or backoff sleeps (constitution §1.1).

### FR5: Storage and refresh
1. A drafted `for_user` entry gains `draft` (text), `draft_status` (`generated` | `unanswered`) and, when
   unanswered, `draft_reason`. Plans without these fields keep working.
2. On plan refresh, a `generated` draft for the same question name and label is kept, not redrafted. `unanswered`
   entries are tried again on the next run.
3. Plans stay readable only by their owner, as they are today (row-level security on `application_fill_plans`).

### FR6: Remote fill
1. Remote fill types each `generated` draft only into the field whose name matches that question.
2. The field stays highlighted as needing review, marked as a draft. Remote fill never clicks Submit (unchanged).
3. If the field can't be found, the draft is skipped and the label is listed as unfilled.
4. JobScanr does not record what the user finally submitted.

## 4. Constitution & Invariant Checks

- [x] Respects database pooler requirements: no new connections; no connection held during Groq calls (FR4.4).
- [x] Respects zero-disk file storage: CV text extracted from in-memory bytes (FR2.1).
- [x] Respects scraper/API rate limits & concurrency pools: one posting at a time as today, Groq retries capped
      at 3 with backoff and a per-run circuit breaker (FR4).
- [x] Respects ATS submission safety gate: drafts are typed into a form the user reviews; the user clicks Submit
      (FR6, constitution §1.5).
- [x] Job descriptions never persisted (FR3.5).

## 5. Acceptance Criteria

Unit tests with `httpx.MockTransport`, no real Groq, Greenhouse or database calls:

1. A successful Groq response becomes a `generated` draft; the request carries the CV text, job description and
   the prompt rules.
2. 429 then success on attempt 2, and on attempt 3, returns a draft; `Retry-After` is respected (sleep mocked).
3. 429 on all 3 attempts returns `unanswered` / `rate_limit_exceeded` without raising, and no further questions
   are sent to Groq that run.
4. A 401 is not retried and yields `unanswered` / `llm_error`.
5. Truncation ends on a full sentence and stays within `max_words` and `max_chars`.
6. Only `open_ended` free-text entries are drafted; selects, `no_confident_answer` and file entries are not.
7. Users who have not opted in, have no CV, have a `.doc` CV or have no `GROQ_API_KEY` get plans with no drafts
   and no Groq requests.
8. A refresh keeps an existing `generated` draft without calling Groq, and retries an `unanswered` one.
9. PDF and DOCX extraction return text from small fixture files built in memory.
10. Remote fill types a draft into the matching field only, and leaves it highlighted (web unit test).
11. `ruff check .`, `ruff format --check .`, `mypy models.py config.py scrapers/`, `pytest tests/` and the web
    checks pass.
