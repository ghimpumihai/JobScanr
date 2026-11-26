# Implementation Tasks: LLM-Drafted Answers for Open-Ended Questions in Remote Fill

**Feature Slug**: `llm-open-question-drafts`  
**Plan Reference**: [.specify/specs/llm-open-question-drafts/plan.md](./plan.md)  
**Spec Reference**: [.specify/specs/llm-open-question-drafts/spec.md](./spec.md)  
**Status**: Completed (2026-11-26)  

Each task adds its own tests. AC numbers refer to spec section 5. Run `.venv/bin/python -m pytest tests/` after
Python, SQL or test edits, and `npm test` and `npm run check` in `web/` after web edits. No task runs live Groq,
Greenhouse, Supabase or database calls.

## Phase 0: Prerequisites
- [x] Task 0.1: Confirm #129 (`spec/remote-browser-apply-spike`) is merged to `main`. If not, STOP.
  (Squash-merged as PR #130 on 2026-11-25; `jobs`, `web/src` and `db` match the spike branch tip.)
- [x] Task 0.2: Create branch `feat/llm-open-question-drafts` from `main`.
- [x] Task 0.3: Add `pypdf` (latest version, pinned) to `requirements.txt` and install it in `.venv`. Installing
  is a network request: ask first.

## Phase 1: Schema & Data Contracts
- [x] Task 1.1: `db/schema.sql`: `ALTER TABLE users ADD COLUMN IF NOT EXISTS llm_drafts_enabled BOOLEAN NOT NULL
  DEFAULT FALSE;`. Add an assertion in `tests/test_apply_schema.py` (or `test_schema_security.py`, whichever
  checks `users` columns) that the column exists with default false. Do not apply to any database.
- [x] Task 1.2: `models.py`: `User` gains `NotRequired` `llm_drafts_enabled: bool` and
  `resume_storage_path: str | None`. `mypy models.py config.py scrapers/` stays clean.
- [x] Task 1.3: `db/queries.py`: `get_active_users` selects `llm_drafts_enabled`; `list_fill_plan_candidates`
  returns `previous_plan` (`p.plan`, decoded the same way as the other JSONB columns). Update the tests that
  mock their rows.

## Phase 2: Core Drafting Module (`jobs/apply/llm_answers.py`)
- [x] Task 2.1 (AC9): `extract_cv_text(data, filename)`: PDF via `pypdf` (first 5 pages), DOCX via `zipfile` +
  `ElementTree` (one line per paragraph); `.doc`, parse errors and text under 200 characters give `None`; result
  capped at `MAX_CV_CHARS`; never raises. Tests in `tests/test_llm_answers.py` with a DOCX and a one-page PDF built
  in memory, a `.doc` header and garbage bytes.
- [x] Task 2.2 (AC5): `truncate_answer(text, max_words, max_chars)`: tests for over words, over characters, no
  sentence end (cuts at a whole word), exact fit, and empty input.
- [x] Task 2.3 (AC1): `draft_open_question_answer`: prompt constants (spec FR3.3 rules, delimited data blocks),
  one POST, response parsing, truncation, empty output counts as `llm_error`. Test with `httpx.MockTransport`:
  the request carries the CV text, description, question, the no-invention rules, model, `max_tokens` and timeout.
- [x] Task 2.4 (AC2, AC3, AC4): Retry policy from plan section 3.2: retry on 429, 5xx, timeout and transport errors;
  `Retry-After` capped at 30 s, else 2 s then 4 s; at most 3 attempts; no retry on other 4xx or malformed JSON.
  `asyncio.sleep` patched. Tests: 429 then success on attempt 2 and on attempt 3; `Retry-After` honored and
  capped; 429 ×3 gives `rate_limit_exceeded`; 500 ×3 gives `llm_error`; 401 is one request and `llm_error`;
  nothing raises. Logs carry no CV, prompt or draft text (check with `caplog`).

## Phase 3: Fill Plan Integration (`jobs/apply/greenhouse.py`, `jobs/apply/fill_plan.py`)
- [x] Task 3.1: `GreenhouseSubmitter`: split `fetch_questions` into `fetch_job` (raw JSON) and `parse_questions`
  (existing parsing); `fetch_questions` returns `parse_questions(await fetch_job(...))`. The existing tests in
  `tests/test_apply_submitters.py` and `tests/test_apply_runner.py` pass unchanged; add one test that `fetch_job`
  returns `content`.
- [x] Task 3.2 (AC6): `build_plan` adds `"type"` to `open_ended` entries. Update
  `test_build_plan_splits_confident_answers_from_questions_for_the_user`.
- [x] Task 3.3 (AC6, AC8): `Drafter` (client, key, model from `GROQ_MODEL` or the default, `tripped`, per-user CV
  cache via `asyncio.to_thread(download_resume_stream, ...)` + `validate_cv` + `extract_cv_text`) and
  `add_drafts(plan, previous_plan, cv_text, job_description, drafter)`. Tests: only `open_ended` long/short text
  entries are drafted (select-type with a long label, `no_confident_answer`, `file` are not); a matching
  `generated` draft is copied with zero requests; `unanswered` is retried; after one exhausted question the next
  question sends nothing and stays without draft fields.
- [x] Task 3.4 (AC3, AC7): `build_fill_plans`: use `fetch_job`, `strip_html(content)` capped at `MAX_JD_CHARS`, and
  call `add_drafts` only when the user opted in, `GROQ_API_KEY` is set (log once if not), and CV text exists. A
  drafting error is caught per posting and the plan is still written. Tests: opted out, no CV, `.doc` CV and no
  key each give plans without drafts and zero Groq requests; a CV is downloaded once for two postings of one user.
- [x] Task 3.5: `.env.example`: one comment line saying remote-fill drafts use `GROQ_API_KEY` and `GROQ_MODEL`.
- Note (2026-11-26, Task 3.3): `add_drafts` takes the `user` instead of `cv_text` and reads the CV through
  `Drafter.cv_text` only when a question needs a new draft. Kept drafts need no CV download, and a failed download
  does not drop them. `.doc` CVs are covered where the CV is loaded (`_load_cv_text`). `build_fill_plans` opens its
  own `httpx.AsyncClient` when the pipeline passes none, so the Groq client is closed after the run.

## Phase 4: Web (`web/`)
- [x] Task 4.1: `src/lib/types/index.ts`: profile gains `llm_drafts_enabled: boolean`. `fill.ts`: `for_user`
  entries gain optional `type`, `draft`, `draft_status`, `draft_reason`; `FillResult` gains `drafted: string[]`.
- [x] Task 4.2 (AC10): `fillPage` types `generated` drafts by `name`/`id` after the planned fields; a missing field
  goes to `unfilled`. `tests/fill-fixtures.test.mjs`: a draft lands only in its own textarea, never in another
  field; a draft whose field is missing is listed as unfilled; `unanswered` entries are not typed.
- [x] Task 4.3 (AC10): `session.ts`: select `llm_drafts_enabled`; strip `draft*` keys when false; drafted labels in
  `leftForUser` read `"<label> (draft typed in, please review)"`. `tests/remote-fill-start.test.mjs` covers both.
- [x] Task 4.4: Settings: load the column and remote-fill availability (`isEnabled()` and `isAllowlisted()`); a
  `saveDrafts` action like `saveAutoApply`; a checkbox with the Groq disclosure, shown only when remote fill is on
  for the user. `tests/settings-actions.test.mjs`: saves true and false; a demo user gets the demo result.
- Note (2026-11-26, Phase 4): the session tests live in `tests/remote-apply-actions.test.mjs` (not
  `remote-fill-start`, which covers the panel helper). Drafts go only into a free-text control (textarea or text
  input, not a select, checkbox, radio, file or combobox). The headless-Chromium tests (`fill-fixtures`,
  `fill-spike`) could not run locally: this WSL machine lacks `libnspr4.so`. CI installs Chromium and runs them.

## Phase 5: Verification
- [x] Task 5.1 (AC11): `.venv/bin/python -m ruff check .`, `ruff format --check .`,
  `mypy models.py config.py scrapers/`, `python -m scripts.validate_seed_schema`, `python -m pytest tests/`.
- [x] Task 5.2 (AC11): in `web/`: `npm test`, `npm run check`, `npm run build`.
- [x] Task 5.3: `graphify update .`.
- [x] Task 5.4: Applying the schema to staging (`python -m scripts.apply_schema --staging`) and production is a
  database write: list it for the user, do not run it.
- Results (2026-11-26): ruff, format, mypy, seed validation clean; pytest 535 passed, 1 deselected. Web: 73 of 109
  `npm test` pass; the 36 headless-Chromium tests fail to launch locally (`libnspr4.so` missing) and are left to CI
  (user decision). `npm run check` 0 errors, `npm run build` passes. Schema not applied anywhere: run
  `python -m scripts.apply_schema --staging`, then `python -m scripts.apply_schema`, before this branch is deployed.

## Converge Findings (2026-11-26)
- Fixed: FR2.2 asked for a logged reason when a CV gives no text; `_load_cv_text` now logs it (test added).
- Open: plan section 1.3 said `digest.yml` already passes `GROQ_API_KEY`. It does only for the link-fixing step.
  The `Scrape careers and notify` step, which builds fill plans, gets no `GROQ_API_KEY`,
  `SUPABASE_SERVICE_ROLE_KEY` or `REMOTE_APPLY_USER_IDS`, so scheduled runs build no plans (already true after
  #129) and could make no drafts.
- Fixed (user decision): that step now gets `REMOTE_APPLY_USER_IDS` (`vars`), `GROQ_API_KEY` and
  `SUPABASE_SERVICE_ROLE_KEY` (`secrets`). Each must exist in the repo's `production` environment; unset means off.

## Live Test (2026-11-26, after convergence)
- Real CV (PDF, 3,289 chars extracted), 3 real Greenhouse postings (Monzo, GitLab, Figma), real Groq; no DB writes.
- Fixed: `llama-3.3-70b-versatile` is retired on Groq (HTTP 404, breaker tripped as designed). Default is now
  `openai/gpt-oss-120b`, matching `scripts/ai_fixer.py`. gpt-oss at default effort used all 400 tokens on reasoning
  (`finish: length`), so it gets `reasoning_effort: "low"` and `max_tokens` is 1000. Tests updated.
- Result: 5/5 questions drafted, 13–135 words each. Most facts match the CV. Problems seen: the company name was
  misspelled once ("Monoku" for Monzo); one invented scale ("tens of thousands of job postings daily", the CV says
  357 boards); an accessibility-adjustments question was answered "I do not require any adjustments", a personal
  fact the CV cannot support; an optional "Additional Information" field got a 135-word pitch.
