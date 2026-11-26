# Feature Specification: Answer Memory for Personal Application Questions

**Feature Slug**: `answer-memory`  
**Status**: Converged (2026-11-26)  
**Issue Reference**: none (requested 2026-11-26 after the #59 live test; builds on `llm-open-question-drafts`)  
**Created**: 2026-11-26  

## 1. Problem Statement & User Value

- **Problem**: Application forms keep asking questions only the candidate can answer: interview adjustments,
  salary expectations, start date, visa or relocation, notice period, "how did you hear about us". Remote fill
  leaves them empty, so the user types the same answers on every form. In the #59 live test (2026-11-26), Groq
  also answered one of them ("I do not require any adjustments") with a fact the CV cannot support.
- **User**: a job seeker on the remote-fill allowlist.
- **Outcome**: the user answers each such question once, in JobScanr. Every later form that asks it, in the same
  words or rephrased, gets the saved answer typed in. The user still reviews the form and clicks Submit
  (constitution §1.5).

## 2. Scope & Boundaries

Decisions made on 2026-11-26:

- Answers are entered in JobScanr, not captured from employer forms.
- A new question is matched to saved ones by exact text first, then by Groq. A Groq match is marked for checking.
- Only personal-fact questions go into memory. Essay questions stay with #59 drafting.
- New spec on the #59 branch, shipped in the same PR. #59 stays converged.

### In Scope
- A per-user list of personal-fact questions, each with an answer or still pending.
- Groq classifies open-ended questions as personal facts (reply `SKIP`) instead of drafting them.
- Pending questions are added automatically when fill plans meet a new personal-fact question.
- Exact-text reuse for every remote-fill user. Groq matching of rephrased questions for users who opted in to drafts.
- A "Saved answers" card in Settings: answer pending questions, edit or delete saved ones.
- Remote fill types saved answers into their questions and marks Groq-matched ones for checking.

### Out of Scope (Pushback)
- **Reading answers back from employer forms**: rejected on 2026-11-26.
- **Essay answers in memory**: they are company-specific ("Why Monzo?"); #59 drafts them per posting.
- **Sending saved answers to Groq**: only question texts are sent. Answers stay in the database.
- **Answering for the user without review**: every answer is typed into a form the user reviews before Submit.
- **Platforms other than Greenhouse**: fill plans exist only for Greenhouse (#129); Lever's and Ashby's public APIs
  give no question list. Kept to Greenhouse on 2026-11-26. Later option: match labels read from the live form at
  fill time on Lever and Ashby (exact text only, pending rows added from the web app).
- **Mapping `screening_defaults` into memory** (work authorization, sponsorship): those already have their own
  fields and mapping; memory covers what they don't.
- **Answer history or versions, sharing answers between users, importing answers**.

## 3. Functional Requirements

### FR1: Personal-fact questions
1. A plan entry is a personal-fact question when:
   - it is open-ended and Groq replied `SKIP` (FR2), or
   - it is a required question with no confident answer (`no_confident_answer`) and is not a file upload.
2. Personal-fact entries have reason `no_confident_answer` in the plan (the name plans already use, so plans built
   before this feature work at once) and are never drafted. (Amended 2026-11-26, was a new `personal` reason.)

### FR2: SKIP rule in drafting (#59 extension)
1. The drafting prompt tells the model to reply exactly `SKIP` when a question asks for something only the candidate
   can know and the CV does not state it: adjustments or accessibility needs, salary, start date or availability,
   visa or relocation, notice period, how they heard about the role, consent or legal attestations.
2. A `SKIP` reply is not a failure. It does not trip the circuit breaker and leaves no draft.

### FR3: Memory store
1. Each user has saved questions, each with question text, an answer (empty while pending), and when it was first
   seen and last changed.
2. Questions are kept once per user by normalized text (lower case, punctuation and repeated spaces removed).
3. At most 200 saved questions per user. Beyond that, new questions are not added and this is logged.
4. Only the owner can read, answer, edit or delete their questions. The pipeline adds pending ones.
5. Answers are never logged and never sent to Groq or any other third party.

### FR4: Matching (pipeline, at plan build)
1. For each personal-fact entry, the pipeline looks for a saved question with the same normalized text. If found,
   the entry is linked to it as an `exact` match.
2. Otherwise, for users who opted in to drafts and when Groq is available, one Groq call is given the new question
   text and the list of saved question texts (no answers), and returns the one that asks the same thing or none.
   A returned question is linked as a `similar` match.
3. The match must ask for the same fact in the same context. Different country, currency or role is a different
   question (for example, UK versus US sponsorship).
4. With no match, the question is added to memory as pending and the entry stays unlinked.
5. Groq matching shares #59's retry policy and per-run circuit breaker. After the breaker trips, only exact matching
   runs for the rest of the run.
6. No database connection is held during Groq calls (constitution §1.1).

### FR5: Remote fill
1. At fill time, remote fill reads the current answer of each linked question, so edits made after the plan was
   built are used.
2. It also exact-matches unlinked personal-fact entries against the user's saved questions at fill time, so an
   answer saved today is used without waiting for the next plan refresh.
3. A saved answer is typed only into its own question's field. For a select, it is used only when it equals one of
   the options' labels (ignoring case); otherwise the question is left for the user.
4. In the drawer's list, `similar` matches read "<label> (saved answer to a similar question, please check)".
   Exact matches are typed without a note. Pending and unmatched questions stay listed as now.
5. A question whose saved answer is empty or was deleted is left for the user.

### FR6: Settings
1. A "Saved answers" card, shown to remote-fill users, lists pending questions first, then answered ones.
2. The user can answer a pending question, edit an answer, or delete a question. Answers are limited to 1,000
   characters.
3. The card says answers stay in JobScanr and are typed into forms that ask the same or a similar question, and that
   only question texts (never answers) go to Groq for matching, and only with drafting turned on.

## 4. Constitution & Invariant Checks

- [x] Respects database pooler requirements: no new connections; none held during Groq calls (FR4.6).
- [x] Respects zero-disk file storage: no files involved.
- [x] Respects scraper/API rate limits & concurrency pools: one Groq call per new personal-fact question, shared
      retries and circuit breaker (FR4.5).
- [x] Respects ATS submission safety gate: answers are typed into forms the user reviews; the user clicks Submit.
- [x] Personal data: answers never leave the database except into the employer's own form (FR3.5).

## 5. Acceptance Criteria

Unit tests with `httpx.MockTransport` and fake Supabase, no live calls:

1. A Groq `SKIP` reply gives the entry reason `no_confident_answer`, leaves no draft, and does not trip the breaker.
2. Required unanswered questions are `no_confident_answer` entries; file uploads and optional ones are not.
   Plans built before this feature get saved answers by exact match at the next fill.
3. An exact (normalized) match links the entry with no Groq call.
4. A rephrased question is linked as `similar` when Groq returns a saved question; the Groq request contains question
   texts and no answers.
5. Groq returning none, an unknown question, or failing leaves the entry unlinked and adds it as pending once.
6. The same new question in two postings adds one pending row.
7. Without the drafts opt-in or a Groq key, only exact matching runs and Groq gets no requests.
8. The 200-question cap stops new pending rows and is logged.
9. Remote fill types the current saved answer (edited after the plan) into its own field only; selects only on an
   option-label match; empty or deleted answers are left for the user; `similar` ones are marked in the drawer.
10. A question answered in Settings today is used at the next fill without a plan refresh (exact match).
11. Settings: answer, edit and delete own questions; another user's rows are not visible or editable; answers over
    1,000 characters are refused; demo mode stores nothing.
12. Database rules: the owner can read, update and delete own rows; inserting rows is backend-only.
13. `ruff check .`, `ruff format --check .`, `mypy models.py config.py scrapers/`, `pytest tests/` and the web
    checks pass.
