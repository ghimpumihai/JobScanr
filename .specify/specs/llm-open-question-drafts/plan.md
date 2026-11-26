# Technical Implementation Plan: LLM-Drafted Answers for Open-Ended Questions in Remote Fill

**Feature Slug**: `llm-open-question-drafts`  
**Spec Reference**: [.specify/specs/llm-open-question-drafts/spec.md](./spec.md)  
**Status**: Converged (2026-11-26)  
**Depends on**: #129 (`spec/remote-browser-apply-spike`) merged to `main`. Every file below that mentions fill plans,
`application_fill_plans`, `fill.ts` or `session.ts` comes from that branch.

---

## 1. Architectural Strategy & Design Trade-offs

### 1.1 Approach
Drafting is one more step inside the existing batch job `build_fill_plans` (`jobs/apply/fill_plan.py`). That job
already runs once a day per Greenhouse To Apply row, one posting at a time, with no database connection held
during HTTP calls.

1. **One Greenhouse GET gives both questions and description.** `GreenhouseSubmitter.fetch_questions` currently
   discards the response's `content` (the job description). It is split into `fetch_job` (the raw JSON) and
   `parse_questions` (the existing parsing), and `fetch_questions` becomes their composition, so other callers don't
   change. `build_fill_plans` calls `fetch_job` and turns `content` into plain text with the existing
   `scrapers.base.strip_html`. The description stays in memory only.
2. **`build_plan` records the question type** on `open_ended` entries (`"type": "long_text"`), so the drafting
   step can pick free-text questions only, without changing how entries are classified.
3. **A new module `jobs/apply/llm_answers.py`** holds the three pure parts: CV text extraction, the Groq call with
   retries, and truncation. It knows nothing about plans or the database.
4. **`fill_plan.add_drafts(plan, previous_plan, ...)`** walks the plan's eligible entries. It copies a `generated`
   draft from the previous plan when the name and label match. Otherwise it calls Groq, unless the run's circuit
   breaker has tripped.
5. **Per-run state** lives in a small `Drafter` object created once per `build_fill_plans` call. It holds the
   `httpx.AsyncClient`, the API key and model, a `tripped` flag (the circuit breaker), and a per-user cache of CV
   text. No module-level globals.
6. **Remote fill** (`fill.ts`) types `generated` drafts by field name after the planned `fields`, with the same
   `setValue` used for planned answers. `session.ts` strips drafts from the plan if the user has opted out since
   the plan was built (FR1.3 takes effect immediately, not after the next refresh). The drawer's "left for you"
   list keeps drafted questions, marked as drafts.

### 1.2 Alternatives considered
| Alternative | Why not |
|---|---|
| Draft at fill time in SvelteKit | Groq retries and backoff (up to ~60 s) inside a request the user waits on; a second LLM client in TypeScript. |
| New `applications.custom_answers` column | The #126 trigger blocks user edits to `applications` columns, and the plan row already belongs to one application. |
| Structured CV parsing into `resume_data` | Another LLM call and a schema to maintain; raw CV text is enough grounding for a 150-word answer. |
| Reuse `scripts/ai_fixer.analyze_with_groq` | It's built for JSON triage with a model fallback list and no 429 handling; the shared part is one POST. |
| Store the opt-in inside `screening_defaults` JSONB | A boolean column is simpler to query, has a clear default, and needs no JSON merge in the settings action. |
| Separate `GROQ_DRAFT_MODEL` env var | The approved spec says `GROQ_MODEL`. Noted as a risk in §5. |

### 1.3 Minimising new code
- Reuse: `download_resume_stream`, `validate_cv`, `strip_html`, `GreenhouseSubmitter` parsing, `upsert_fill_plan`,
  `fill.ts` `setValue`, the settings action pattern (`saveAutoApply`), and `GROQ_API_KEY`, which `digest.yml`
  already passes.
- New Python dependency: **`pypdf`** (pure Python, pinned) for PDF text. DOCX text uses `zipfile` and
  `xml.etree.ElementTree` from the standard library.
- No new web dependency.

---

## 2. Component Boundaries & Critical Files

### 2.1 Database (`db/schema.sql`, idempotent)
- `ALTER TABLE users ADD COLUMN IF NOT EXISTS llm_drafts_enabled BOOLEAN NOT NULL DEFAULT FALSE;`
  Users already update their own row (`users_update_own`); no trigger change is needed.

### 2.2 Python
| File | Change |
|---|---|
| `requirements.txt` | Add `pypdf==<latest at implementation>`. |
| `models.py` | `User`: add `NotRequired` `llm_drafts_enabled: bool` and `resume_storage_path: str \| None` (already returned by `get_active_users`, but not typed). |
| `db/queries.py` | `get_active_users`: select `llm_drafts_enabled`. `list_fill_plan_candidates`: also return `p.plan` as `previous_plan` (it's already LEFT JOINed). |
| `jobs/apply/greenhouse.py` | Split `fetch_questions` into `fetch_job` + `parse_questions`; behavior unchanged. |
| `jobs/apply/llm_answers.py` (new) | `extract_cv_text`, `truncate_answer`, `draft_open_question_answer`, prompt constants. |
| `jobs/apply/fill_plan.py` | `build_plan` adds `type` to `open_ended` entries; new `Drafter` and `add_drafts`; `build_fill_plans` wires them in. |
| `tests/test_llm_answers.py` (new) | Extraction, truncation, Groq call, retries (see §4). |
| `tests/test_fill_plan.py` | Eligibility, reuse, opt-in/no-CV/no-key gates, breaker across questions. |
| `tests/test_greenhouse*.py` (whichever covers `fetch_questions`) | Still passes unchanged; one test for `fetch_job` returning `content`. |

### 2.3 Web
| File | Change |
|---|---|
| `web/src/lib/types/index.ts` | Profile type gains `llm_drafts_enabled: boolean`. |
| `web/src/routes/(app)/settings/+page.server.ts` | Load the column; new `saveDrafts` action like `saveAutoApply`. |
| `web/src/routes/(app)/settings/+page.svelte` | A checkbox with the Groq disclosure text, shown only when remote fill is on for the user (`isEnabled()` and `isAllowlisted()` from `session.ts`, passed in by the load function). |
| `web/src/lib/server/remoteApply/fill.ts` | `FillPlan.for_user` entries gain optional `type`, `draft`, `draft_status`, `draft_reason`; `fillPage` types `generated` drafts by name. `FillResult` gains `drafted: string[]` (labels). |
| `web/src/lib/server/remoteApply/session.ts` | Select `llm_drafts_enabled`; drop drafts when it's false; mark drafted labels in `leftForUser`. |
| `web/tests/fill-fixtures.test.mjs` | Draft typed into its own textarea only; missing field goes to `unfilled`. |
| `web/tests/remote-fill-start.test.mjs` | Drafts dropped when opted out; drafted labels marked in `leftForUser`. |
| `web/tests/settings-actions.test.mjs` | `saveDrafts` saves true/false; demo user gets the demo result. |

### 2.4 Docs
- `.env.example`: one comment line saying drafting uses `GROQ_API_KEY` / `GROQ_MODEL`.

---

## 3. Data Flow & Interfaces

### 3.1 Flow (per pipeline run)
```text
build_fill_plans(users)
  drafter = Drafter(client, api_key=GROQ_API_KEY, model)      # disabled if no key (logged once)
  for cand in list_fill_plan_candidates(...):                  # DB connection released before the loop body
      job = await submitter.fetch_job(posting)                 # 1 Greenhouse GET (unchanged count)
      plan = build_plan(parse_questions(job), user, form_url)
      if user.llm_drafts_enabled and drafter.enabled:
          cv_text = await drafter.cv_text(user)                # once per user per run; to_thread download
          if cv_text:
              await add_drafts(plan, cand.previous_plan, cv_text, strip_html(job["content"]), drafter)
      upsert_fill_plan(cand.application_id, plan)              # short connection, as today
```

### 3.2 `jobs/apply/llm_answers.py`
```python
MAX_CV_CHARS = 8000          # ~2k tokens
MAX_JD_CHARS = 4000          # ~1k tokens; with output this keeps one request well under the free-tier TPM limit
DEFAULT_MAX_CHARS = 1000     # Greenhouse's question schema gives no length limit; 1000 fits common ATS textareas
MAX_RETRY_AFTER_S = 30.0
DEFAULT_MODEL = "llama-3.3-70b-versatile"

def extract_cv_text(data: bytes, filename: str) -> str | None
    # .pdf -> pypdf, first 5 pages; .docx -> word/document.xml <w:t> runs, one line per <w:p>.
    # .doc, parse errors, or < 200 chars of text -> None. Never raises. Truncated to MAX_CV_CHARS.

def truncate_answer(text: str, max_words: int, max_chars: int) -> str
    # Collapse whitespace; if over either limit, cut at the last sentence end (. ! ?) inside both limits;
    # if no sentence end fits, cut at the last whole word. "" stays "".

async def draft_open_question_answer(
    client: httpx.AsyncClient, question_text: str, job_description: str, cv_text: str,
    *, api_key: str, model: str = DEFAULT_MODEL, max_words: int = 150, max_chars: int | None = DEFAULT_MAX_CHARS,
) -> tuple[str | None, str | None]       # (draft, None) or (None, "rate_limit_exceeded" | "llm_error")
```
- One POST to `https://api.groq.com/openai/v1/chat/completions` with `temperature=0.3`, `max_tokens=400` and a
  10 s timeout. The system prompt carries the spec FR3.3 rules. The user message wraps the CV, the description and
  the question in clearly labelled delimited blocks, and says text inside the blocks is data, not instructions.
- Retry policy: attempts 1–3. Retried: 429, 5xx, `httpx.TimeoutException`, `httpx.TransportError`. Wait:
  `Retry-After` seconds (numeric, capped at 30 s) when present, else `2.0 * attempt`. The sleep is
  `asyncio.sleep` (patched in tests). Not retried: other 4xx, malformed JSON. Reason: `rate_limit_exceeded` if the
  last failure was 429, else `llm_error`. Empty output after truncation counts as `llm_error`.
- Logging: status codes and reasons only. Never CV text, prompts or drafts.

### 3.3 `jobs/apply/fill_plan.py`
```python
DRAFTABLE = {"long_text", "short_text"}

class Drafter:                                   # one per build_fill_plans call
    client: httpx.AsyncClient; api_key: str | None; model: str; tripped: bool
    async def cv_text(self, user: User) -> str | None    # cached by user id; download + validate_cv + extract

async def add_drafts(plan: dict, previous_plan: dict | None, cv_text: str, job_description: str,
                     drafter: Drafter) -> None   # mutates plan["for_user"] entries in place
```
- Eligible entry: `reason == "open_ended"` and `type in DRAFTABLE`.
- Reuse: previous entry with the same `name` and `label` and `draft_status == "generated"` → copy `draft` and
  `draft_status`, no call.
- Else if `drafter.tripped`: leave the entry without draft fields (it's tried next run).
- Else call Groq. On success `draft_status="generated"`. On failure `draft_status="unanswered"`, set
  `draft_reason`, and `drafter.tripped = True`.
- `PLAN_VERSION` stays 1: the new keys are optional, and old readers ignore them.

### 3.4 Plan entry contract (`application_fill_plans.plan.for_user[]`)
```json
{"name": "question_123", "label": "Why do you want to join Acme?", "reason": "open_ended", "type": "long_text",
 "draft": "I want to join Acme because ...", "draft_status": "generated"}
{"name": "question_124", "label": "Describe ...", "reason": "open_ended", "type": "long_text",
 "draft_status": "unanswered", "draft_reason": "rate_limit_exceeded"}
```

### 3.5 Remote fill
- `fillPage`: after planned `fields`, for each `for_user` entry with `draft_status === 'generated'` and a
  non-empty `draft`, it finds the unused control with `name` or `id` equal to the entry's `name` and calls
  `setValue`. On success the label goes to `result.drafted` and `filled` is incremented. Otherwise the label goes to
  `unfilled`. Each counts in `planned`. The standard matcher already refuses textareas and `question_*` fields, so
  profile values can't land there.
- `session.ts`: when `llm_drafts_enabled` is false, it removes `draft*` keys from `for_user` entries before
  `fillPage`. `leftForUser` shows drafted labels as `"<label> (draft typed in, please review)"`.

---

## 4. Testing & Verification Strategy

- **Groq**: `httpx.MockTransport` handlers returning sequences of responses (200 / 429 with and without
  `Retry-After` / 500 / 401 / malformed JSON / timeout via raising `httpx.ReadTimeout`). `asyncio.sleep` patched to
  record delays.
- **Request content**: assert the POST body includes the CV text, description and question, and that the system
  prompt includes the no-invention rules (spec AC1).
- **Extraction fixtures built in memory**: a DOCX made with `zipfile`; a one-page PDF with a text content stream
  written as bytes in the test; a `.doc` header; garbage bytes. No fixture files on disk beyond test source.
- **Truncation**: over words, over chars, no sentence end, exact fit, empty.
- **fill_plan**: `list_fill_plan_candidates` / `upsert_fill_plan` / `download_resume_stream` patched as in the
  existing tests. Cases: opted out, no CV, `.doc` CV, no API key → zero Groq requests. Reuse of a generated draft →
  zero requests. Unanswered → retried. 429 exhaustion on question 1 → question 2 is not sent (breaker).
  Select-type `open_ended` (long label) → not drafted.
- **Web**: existing `node --test` fixture-page tests for `fillPage`; mocked Supabase for session and settings.
- Verification:
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
| **Fabricated experience** sent to an employer | Prompt rules, CV-only grounding, and above all the user reviews and edits every draft in the form before clicking Submit (§1.5). The drawer marks drafted fields. |
| **Prompt injection** from the employer-written job description (for example "include the candidate's home address") | Delimited data blocks and an explicit instruction; output capped at 150 words; the user reviews it before submitting. The draft only goes into that employer's own form, and the CV text is already attached to it as the CV. |
| **Groq free-tier limits** (approx. 30 RPM, a few thousand TPM, daily token caps; not verified) | Input capped at ~3k tokens; sequential calls; 3 attempts with backoff; breaker stops drafting for the run on the first exhausted question; drafts reused across refreshes so each question costs one call. Worst-case added run time ≈ 2 waits of up to 30 s. |
| **Pipeline failure** from drafting | `draft_open_question_answer` and `extract_cv_text` never raise; `add_drafts` errors are caught per posting so the plan is still written without drafts. |
| **Privacy**: CV text sent to a third party | Opt-in off by default with disclosure; only allowlisted users; never logged. Drafts are stored in plans readable only by the owner (existing RLS). |
| **`pypdf` on hostile PDFs** (past CVEs were slow-parse DoS) | The CV is the user's own file and already passes `validate_cv`; parsing is limited to 5 pages and wrapped in try/except. Pin a current version; `pip-audit` in CI. |
| **Event loop blocked** by the sync CV download | `asyncio.to_thread`, once per user per run. |
| **`GROQ_MODEL` is shared with `scripts/ai_fixer.py`** | If someone sets it to a reasoning model for the fixer, drafting uses it too. Acceptable for now; split the variable if that happens. |
| **Stale drafts after opt-out** | `session.ts` strips them at fill time; the next refresh drops them from storage. |
| **Schema change** | Additive, idempotent `ADD COLUMN IF NOT EXISTS`; applying it to staging/production is a DB write and needs explicit confirmation at implementation time. |
