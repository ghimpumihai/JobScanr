# Implementation Tasks: Greenhouse and Lever Submitters with Question Schema Mapping

**Feature Slug**: `greenhouse-lever-submitters`  
**Plan Reference**: [.specify/specs/greenhouse-lever-submitters/plan.md](./plan.md)  
**Status**: Completed  

---

## Phase 1: Models, Schemas & Core Data Contracts
- [x] Task 1.1: Define `QuestionType`, `QuestionOption`, `ScreeningQuestion`, `SubmissionResult`, and `SubmitResponse` in `jobs/apply/base.py`.
- [x] Task 1.2: Implement question classification and mapping heuristics in `jobs/apply/base.py` for work authorization, visa sponsorship, years of experience, notice period, location, and candidate profile URLs.
- [x] Task 1.3: Define abstract `BaseSubmitter` contract with `fetch_questions`, `map_and_validate_payload`, `submit`, and `preview_submission`.

## Phase 2: Greenhouse Submitter Implementation
- [x] Task 2.1: Implement `GreenhouseSubmitter.fetch_questions` querying `GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{id}?questions=true` and parsing questions and options.
- [x] Task 2.2: Implement `GreenhouseSubmitter.map_and_validate_payload` converting applicant profile and screening answers into Greenhouse multipart fields (`first_name`, `last_name`, `email`, `phone`, `question_{id}`).
- [x] Task 2.3: Implement `GreenhouseSubmitter.submit` dispatching multipart POST with in-memory resume stream and handling 200/201, 400 captcha, 404 closed, and 429/5xx error responses.

## Phase 3: Lever Submitter Implementation
- [x] Task 3.1: Implement `LeverSubmitter.fetch_questions` querying `GET https://api.lever.co/v0/postings/{company}/{id}?mode=json` and parsing custom card fields and consent terms.
- [x] Task 3.2: Implement `LeverSubmitter.map_and_validate_payload` converting applicant profile into Lever multipart fields (`name`, `email`, `phone`, `org`, `urls`, `comments`, `cards[{card_id}][{field_id}]`, `consent`).
- [x] Task 3.3: Implement `LeverSubmitter.submit` dispatching multipart POST with in-memory resume stream and handling 200, 400 captcha, 404 closed, and error responses.

## Phase 4: Integration & Exports
- [x] Task 4.1: Export submitters and models in `jobs/apply/__init__.py`.
- [x] Task 4.2: Implement factory / registry function `get_submitter(platform: str, client: httpx.AsyncClient | None = None) -> BaseSubmitter`.

## Phase 5: Verification & Test Suite
- [x] Task 5.1: Write unit tests for base mapping logic in `tests/test_apply_submitters.py`.
- [x] Task 5.2: Write unit tests for Greenhouse question fetching, payload mapping, submission, captcha fallback, and 404 closed handling with mocked responses.
- [x] Task 5.3: Write unit tests for Lever question fetching, cards mapping, submission, captcha fallback, and 404 closed handling with mocked responses.
- [x] Task 5.4: Run `ruff check .`, `ruff format --check .`, and `mypy`.
- [x] Task 5.5: Run full test suite `python -m pytest tests/`.
