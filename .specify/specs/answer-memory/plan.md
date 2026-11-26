# Technical Implementation Plan: Answer Memory for Personal Application Questions

**Feature Slug**: `answer-memory`  
**Spec Reference**: [.specify/specs/answer-memory/spec.md](./spec.md)  
**Status**: Converged (2026-11-26)  
**Depends on**: `llm-open-question-drafts` (#59), on the same branch `feat/llm-open-question-drafts`.

---

## 1. Architectural Strategy & Design Trade-offs

### 1.1 Approach
1. **One new table, `user_answers`**, one row per saved question per user. The pipeline inserts pending rows; the
   owner reads, answers, edits and deletes through the web app under row-level security.
2. **Classification stays in the plan builder.** Personal-fact entries keep the reason plans already use,
   `no_confident_answer` (required, nothing could answer it). `add_drafts` gives an open-ended entry that reason
   when Groq replies `SKIP`. No rename, so plans built before this feature get exact-match answers at once.
3. **Linking happens in the batch, answers are read at fill time.** A new `add_memory_links(plan, ...)` in
   `fill_plan.py` sets `memory_id` and `memory_match` (`exact` | `similar`) on personal entries and returns the
   question texts to add as pending. The plan stores the link, never the answer. `session.ts` reads the current
   answers when the user opens remote fill, so edits apply at once and answers never sit in plan JSON.
4. **Fill-time exact matching** in `session.ts` covers questions answered after the plan was built (FR5.2), with the
   same normalization as Python.
5. **Groq calls share one helper.** The retry loop in `draft_open_question_answer` moves into `_chat(...)`;
   drafting and the new `match_saved_question` both use it, so both obey the same retries and the run's breaker
   (`Drafter.tripped`).
6. **Previous links are kept on refresh**, like drafts: same name and label and the saved row still exists means no
   new Groq call.

### 1.2 Alternatives considered
| Alternative | Why not |
|---|---|
| Answers stored inside the plan JSON | Stale until the next daily refresh; copies sensitive answers into every plan row. |
| JSONB list on `users` | The web app would rewrite the whole list on every edit, racing the pipeline's inserts; no per-row rules. |
| Groq matching at fill time in the web app | Seconds of latency while the user waits, and a second Groq client in TypeScript. |
| Embeddings or fuzzy string matching | A new dependency or tuning for a list capped at 200; one Groq call per new question is enough. |
| Send saved answers to Groq to help matching | Answers are personal data; matching needs only the question texts (spec FR3.5). |

### 1.3 Minimising new code
- Reuse: `Drafter` (client, key, model, breaker), the #59 retry loop, `build_plan` reasons, the plan `for_user`
  entry shape, `fill.ts` `setValue`/`pickOption`, the settings action pattern, the RLS policy pattern of
  `remote_apply_sessions`.
- No new dependency.

---

## 2. Component Boundaries & Critical Files

### 2.1 Database (`db/schema.sql`, idempotent)
```sql
CREATE TABLE IF NOT EXISTS user_answers (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id        BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    question       TEXT NOT NULL CHECK (char_length(question) <= 500),
    question_key   TEXT NOT NULL,
    answer         TEXT CHECK (answer IS NULL OR char_length(answer) <= 1000),
    first_seen_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at     TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (user_id, question_key)
);
```
- RLS on; policies `select_own`, `update_own`, `delete_own` (row's `user_id` belongs to `auth.uid()`), as for
  `remote_apply_sessions`.
- `REVOKE ALL ... FROM anon`; `REVOKE INSERT, UPDATE, TRUNCATE ... FROM authenticated`;
  `GRANT UPDATE (answer, updated_at) ... TO authenticated`. The user cannot rename a question or move it to
  another user; inserts are backend-only (spec AC12).

### 2.2 Python
| File | Change |
|---|---|
| `db/queries.py` | `get_user_answers(user_ids) -> dict[int, list[dict]]` (id, question, question_key, has_answer); `add_pending_questions(user_id, questions) -> int` with `ON CONFLICT (user_id, question_key) DO NOTHING`. |
| `jobs/apply/llm_answers.py` | `normalize_question(text)`; `_chat(...)` extracted from `draft_open_question_answer`; `SKIP` rule in `SYSTEM_PROMPT` and `"skip"` result; `match_saved_question(...)`. |
| `jobs/apply/fill_plan.py` | `add_drafts`: `"skip"` makes the entry `no_confident_answer`, no breaker; new `add_memory_links`; `build_fill_plans` loads memory once, links, inserts pending rows. |
| `tests/test_llm_answers.py` | `_chat` refactor keeps every existing test green; SKIP, matching, normalization. |
| `tests/test_fill_plan.py` | SKIP reason; linking, pending inserts, cap, reuse, gates. |
| `tests/test_schema_security.py` | Table, RLS policies, revokes and the column grant. |
| `tests/fixtures/question_keys.json` (new) | Shared normalization cases, read by the Python and web tests so both sides agree. |

### 2.3 Web
| File | Change |
|---|---|
| `src/lib/server/remoteApply/fill.ts` | `normalizeQuestion`; `ForUserField` gains `memory_id`, `memory_match`, `memory_answer`; `fillPage` types memory answers (free text, select, combobox); `FillResult` gains `remembered: { label: string; similar: boolean }[]`; selects and dropdown options match ignoring case. |
| `src/lib/server/remoteApply/session.ts` | Load the user's `user_answers` once; set `memory_answer` on personal entries by `memory_id`, else by exact key; build `leftForUser` (exact fills drop out, similar ones get the note). |
| `src/routes/(app)/settings/+page.server.ts` | Load own answers (pending first); `saveAnswer` (id, text ≤ 1,000) and `deleteAnswer` (id) actions. |
| `src/routes/(app)/settings/+page.svelte` | "Saved answers" card for remote-fill users. |
| `src/lib/types/index.ts` | `SavedAnswer` type. |
| `tests/fill-fixtures.test.mjs` | Memory answers typed into own field; select only on a case-insensitive option match. |
| `tests/remote-apply-actions.test.mjs` | Fresh answers by id, exact fallback, empty/deleted left, drawer text. |
| `tests/settings-actions.test.mjs` | Save, edit, delete, length limit, other user's id, demo mode. |
| `tests/question-keys.test.mjs` (new) | `normalizeQuestion` against the shared fixture. |

---

## 3. Data Flow & Interfaces

### 3.1 Flow (per pipeline run)
```text
build_fill_plans(users)
  memory = queries.get_user_answers(allowlisted ids)          # one short query; connection released
  for each candidate:
      plan = build_plan(...)                                   # required unanswered -> "no_confident_answer"
      add_drafts(...)                                          # opted in: SKIP -> "no_confident_answer", no breaker
      new = await add_memory_links(plan, previous_plan, memory[user], drafter, use_groq=opted_in and key)
      queries.add_pending_questions(user_id, new)              # short connection; also appended to memory[user]
      queries.upsert_fill_plan(...)
```

### 3.2 `llm_answers.py`
```python
def normalize_question(text: str) -> str
    # lower case; every char that is not a letter, digit or space becomes a space; spaces collapsed; trimmed.
    # Unicode-aware (str.isalnum), so "Ești disponibil?" keeps its letters. Max 500 chars.

async def _chat(client, messages, *, api_key, model, max_tokens) -> tuple[str | None, str | None]
    # The #59 retry loop, unchanged: (content, None) or (None, "rate_limit_exceeded" | "llm_error").

async def draft_open_question_answer(...)   # same signature; uses _chat; "SKIP" -> (None, "skip")

async def match_saved_question(client, question: str, saved: list[str], *, api_key, model)
        -> tuple[int | None, str | None]
    # One call. Prompt: numbered saved questions; "Reply with the number of the saved question that asks for the
    # same fact in the same context (same country, currency, role), or NONE." Parse the first integer in range;
    # NONE or out of range -> (None, None). Errors -> (None, reason). max_tokens 200.
```
- SKIP detection: the reply, stripped of whitespace and trailing punctuation, equals `SKIP` ignoring case.

### 3.3 `fill_plan.py`
```python
MEMORY_CAP = 200

async def add_memory_links(plan, previous_plan, saved: list[dict], drafter: Drafter, use_groq: bool) -> list[str]
```
For each `no_confident_answer` entry (free text or select; `file` entries have their own reason):
1. Previous plan has the same name and label with a `memory_id` still in `saved` → copy `memory_id`, `memory_match`.
2. Else exact `normalize_question(label)` hit in `saved` → `memory_match = "exact"`.
3. Else, if `use_groq`, not `drafter.tripped`, and `saved` is not empty → `match_saved_question(label, saved
   questions)`. A hit is `"similar"`. On error, `drafter.tripped = True`; the entry stays unlinked.
4. Else the label is returned as new, once per key, unless `len(saved) + new >= MEMORY_CAP` (log once per user).

Pending rows are matched too (a link to a pending row fills nothing until the user answers it), so a rephrased
question does not add a second pending row.

### 3.4 Plan entry contract (additions)
```json
{"name": "question_7", "label": "What are your salary expectations?", "reason": "no_confident_answer",
 "type": "short_text", "memory_id": 42, "memory_match": "similar"}
```

### 3.5 Fill time (`session.ts`, `fill.ts`)
- `session.ts`: `select id, question_key, answer from user_answers` (own rows by RLS). For each `no_confident_answer` entry, in new and old plans alike:
  answer by `memory_id` if that row exists; else by `normalizeQuestion(label)`, treated as `exact`. A non-empty
  answer becomes `memory_answer`; `memory_match` is kept for the drawer.
- `fillPage`: after drafts, for entries with `memory_answer`, find the control by name/id. Text inputs and textareas
  are filled. Selects and comboboxes use `setValue` with `option_label` set to the answer, and both option lookups
  ignore case (native: match against the options' text; combobox: `getByRole('option', { name: /^…$/i })`).
  Checkbox, radio and file are skipped. Typed answers go to `result.remembered`, others to `unfilled`.
- `leftForUser`: `no_confident_answer` entries filled from an exact match are dropped; similar ones read
  `"<label> (saved answer to a similar question, please check)"`; drafts as in #59; duplicates removed.

### 3.6 Settings
- `load`: own `user_answers` ordered by `answer IS NULL DESC, first_seen_at`; `remoteApply` already returned.
- `saveAnswer`: `id` integer, `answer` trimmed, 1–1,000 chars → `update({ answer, updated_at })` filtered on `id`.
  RLS limits it to own rows; zero rows updated returns 404.
- `deleteAnswer`: `id` integer → delete filtered on `id`; zero rows returns 404.
- Card: pending questions with a text field each, then answered ones (editable, deletable), and the spec FR6.3 text.

---

## 4. Testing & Verification Strategy

- Groq: `httpx.MockTransport` sequences, `asyncio.sleep` patched; the existing #59 retry tests run against `_chat`
  through `draft_open_question_answer` unchanged.
- Matching: a request lists the saved question texts and contains no answers; reply parsing (`2`, `2.`, `NONE`,
  `7` out of range, empty).
- Normalization parity: one JSON fixture of input/output pairs (punctuation, case, Unicode letters, repeated spaces,
  required asterisks) used by `pytest` and `node --test`.
- `fill_plan`: patched `get_user_answers` / `add_pending_questions` / `upsert_fill_plan`; cases from spec AC1–AC8.
- Web: fake Supabase extended with `user_answers`; Chromium fixture test for typing (runs in CI; local Chromium is
  missing `libnspr4.so`).
- Commands:
  ```bash
  .venv/bin/python -m ruff check .
  .venv/bin/python -m ruff format --check .
  .venv/bin/python -m mypy models.py config.py scrapers/
  .venv/bin/python -m pytest tests/
  cd web && npm test && npm run check
  ```

---

## 5. Risk Assessment & Safety Circuit Breakers

| Risk | Safeguard |
|---|---|
| **Wrong reuse** (UK vs US sponsorship, a different salary currency) | Groq matches only "same fact, same context"; similar matches are marked in the drawer; the user reviews before Submit. Exact matches are on normalized full text only. |
| **Sensitive answers** (health adjustments, salary, visa) | Own-row RLS; inserts backend-only; user may update only `answer`/`updated_at`; never logged; never sent to Groq; not copied into plans. |
| **Pending list grows without bound** | 200 per user; rephrasings link to the existing pending row via Groq. |
| **Groq quota** | One call per new personal question, links reused across refreshes, shared breaker. |
| **Plans built before this feature** | No reason rename: old plans' `no_confident_answer` entries get exact-match answers at the next fill. Similar (Groq) links come from the batch, so they reach old plans at their next daily refresh. |
| **Python and TypeScript normalization differ** | One shared fixture tested on both sides. |
| **Schema change** | Additive and idempotent; applying it to staging and production is a database write and needs your confirmation. |
