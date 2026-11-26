# Implementation Tasks: Answer Memory for Personal Application Questions

**Feature Slug**: `answer-memory`  
**Plan Reference**: [.specify/specs/answer-memory/plan.md](./plan.md)  
**Spec Reference**: [.specify/specs/answer-memory/spec.md](./spec.md)  
**Status**: Completed (2026-11-26)  

Each task adds its own tests. AC numbers refer to spec section 5. Run `.venv/bin/python -m pytest tests/` after
Python, SQL or test edits, and `npm test` and `npm run check` in `web/` after web edits. No task runs live Groq,
Greenhouse, Supabase or database calls. Work continues on `feat/llm-open-question-drafts` (spec section 2).

## Phase 1: Schema & Data Contracts
- [x] Task 1.1 (AC12): `db/schema.sql`: `user_answers` table, unique `(user_id, question_key)`, length checks, RLS
  on, `select_own` / `update_own` / `delete_own` policies, revokes, and `GRANT UPDATE (answer, updated_at)` to
  `authenticated`, as in plan section 2.1. Static checks in `tests/test_schema_security.py`. Do not apply anywhere.
- [x] Task 1.2 (AC3): `normalize_question` in `jobs/apply/llm_answers.py` and `normalizeQuestion` in
  `web/src/lib/server/remoteApply/fill.ts`, both checked against one new fixture `tests/fixtures/question_keys.json`
  (punctuation, case, Unicode letters, repeated spaces, required asterisks, 500-char cap). Python test in
  `tests/test_llm_answers.py`; web test `web/tests/question-keys.test.mjs`.
- [x] Task 1.3 (AC6, AC8): `db/queries.py`: `get_user_answers(user_ids)` and `add_pending_questions(user_id,
  questions)` (`ON CONFLICT DO NOTHING`, returns rows added). Mocked-cursor tests in `tests/test_fill_plan.py`.

## Phase 2: Groq (`jobs/apply/llm_answers.py`)
- [x] Task 2.1: Extract the retry loop into `_chat(client, messages, *, api_key, model, max_tokens)`;
  `draft_open_question_answer` keeps its signature and behavior. All existing tests pass unchanged.
- [x] Task 2.2 (AC1): SKIP rule in `SYSTEM_PROMPT` (spec FR2.1 list); a reply that is `SKIP` (any case, trailing
  punctuation) returns `(None, "skip")`. Tests: `SKIP`, `skip.`, a draft that merely contains the word "skip".
- [x] Task 2.3 (AC4, AC5): `match_saved_question(client, question, saved, *, api_key, model)`: numbered list, "same
  fact, same context" rule, `max_tokens` 200; parse a number in range, `NONE`, out of range, empty; errors keep the
  retry policy. Test that the request holds the question texts and no answers.

## Phase 3: Fill Plan Integration (`jobs/apply/fill_plan.py`)
- [x] Task 3.1 (AC1, AC2): `add_drafts`: a `"skip"` result sets the entry's reason to `no_confident_answer`, adds no
  draft fields, and leaves `drafter.tripped` false.
- [x] Task 3.2 (AC3–AC8): `add_memory_links(plan, previous_plan, saved, drafter, use_groq)` per plan section 3.3:
  reuse of previous links whose row still exists, exact match, Groq similar match (breaker on error), new questions
  once per key, the 200 cap (logged once per user), `file` entries ignored.
- [x] Task 3.3 (AC6, AC7): `build_fill_plans`: load memory once, call `add_memory_links` after `add_drafts`
  (`use_groq` = opted in and key set), insert pending rows and append them to the in-memory list, then upsert the
  plan. A memory error is caught per posting and the plan is still written. Tests: opted out or no key sends
  nothing to Groq; two postings with the same new question add one pending row.

## Phase 4: Web
- [x] Task 4.1: Types: `SavedAnswer` in `src/lib/types/index.ts`; `ForUserField` gains `memory_id`,
  `memory_match`, `memory_answer`; `FillResult` gains `remembered`.
- [x] Task 4.2 (AC9): `fill.ts`: type `memory_answer` into its own field (text, textarea, select, combobox; never
  checkbox, radio or file); native select and dropdown options match ignoring case. `web/tests/fill-fixtures.test.mjs`:
  own field only; select on a case-insensitive match; no match leaves it empty and listed as unfilled. (Chromium
  test: runs in CI.)
- [x] Task 4.3 (AC9, AC10): `session.ts`: load own `user_answers`; answer by `memory_id`, else exact key; empty or
  deleted answers left; `leftForUser` drops exact fills and marks similar ones. Tests in
  `web/tests/remote-apply-actions.test.mjs` with the fake Supabase extended for `user_answers`, including an old plan
  with no `memory_id`.
- [x] Task 4.4 (AC11): Settings: load own answers (pending first); `saveAnswer` and `deleteAnswer` actions with the
  limits in plan section 3.6; "Saved answers" card for remote-fill users with the spec FR6.3 text. Tests in
  `web/tests/settings-actions.test.mjs`: save, edit, delete, over 1,000 chars refused, unknown or other user's id
  gives 404, demo mode stores nothing. Run the Svelte autofixer on the card.

## Phase 5: Verification
- [x] Task 5.1 (AC13): `ruff check .`, `ruff format --check .`, `mypy models.py config.py scrapers/`,
  `python -m scripts.validate_seed_schema`, `python -m pytest tests/`.
- [x] Task 5.2 (AC13): in `web/`: `npm test` (Chromium tests left to CI), `npm run check`, `npm run build`.
- [x] Task 5.3: `graphify update .`.
- [x] Task 5.4: Apply `db/schema.sql` to staging (`python -m scripts.apply_schema --staging`), check that
  `users.llm_drafts_enabled` and `user_answers` with its policies exist, then apply it to production
  (`python -m scripts.apply_schema`) and check the same. Authorized by the user on 2026-11-26. The file is idempotent
  and covers #59's column too. Report the output; stop if either apply fails.

## Results (2026-11-26)
- Python: ruff, format, mypy (core), seed validation clean; pytest 580 passed, 1 deselected.
- Web: 79 of 116 `npm test` pass; the 37 headless-Chromium tests (including the new saved-answer typing test) cannot
  launch locally (`libnspr4.so` missing) and are left to CI. `npm run check` 0 errors, `npm run build` passes.
- Schema applied to staging, then production (12:09 UTC+2). Both checked read-only: `users.llm_drafts_enabled`
  (default false), `user_answers` with RLS on, 3 policies, `authenticated` may update `answer` but not `question`,
  no insert, no `anon` access.

## Converge (2026-11-26)
- Every FR and AC checked against the code. Gap closed: AC7's "no Groq key" case had no build-level test; the
  opt-in test is now parameterized over both (pytest 581).
- Not verified here: AC9's typing test runs in headless Chromium (CI only on this machine); the SKIP rule and the
  matching prompt are tested against mocked replies, not the live model.
