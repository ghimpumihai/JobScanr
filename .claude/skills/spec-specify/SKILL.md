---
name: spec-specify
description: Create or refine a structured functional specification in .specify/specs/<slug>/spec.md based on GitHub Spec Kit standards.
---

# Spec-Driven Development: Specify

Use this skill to draft, inspect, or refine a functional specification before planning or writing code.

## Workflow

1. **Identify Feature Slug**:
   - Determine or prompt for a clear, lowercase kebab-case slug for the feature (e.g. `pdf-resume-generator`, `resilient-queue-worker`).
   - Feature specification directory: `.specify/specs/<slug>/`.

2. **Check Constitution Invariants**:
   - Read `.specify/constitution.md` to ensure proposed functionality respects core invariants (IPv4 pooler, zero-disk PDF storage, live network safety gates, scraper concurrency limits, ATS submission gates).

3. **Draft or Update `.specify/specs/<slug>/spec.md`**:
   The specification must contain:
   ```markdown
   # Feature Specification: <Title>

   **Feature Slug**: `<slug>`  
   **Status**: Draft | Approved | In Progress | Converged  
   **Issue Reference**: #<number> (if applicable)  
   **Created**: YYYY-MM-DD  

   ## 1. Problem Statement & User Value
   - What problem does this solve?
   - Who is the user (job seeker, background worker, system administrator)?
   - What is the expected outcome?

   ## 2. Scope & Boundaries
   - **In Scope**: Explicit features and behaviors included.
   - **Out of Scope (Pushback)**: Features deliberately deferred or omitted (adhering to Ponytail principles: minimum complete solution).

   ## 3. Functional Requirements
   - Explicit system behaviors, inputs, outputs, and state transitions.
   - Error handling, timeouts, and edge cases.

   ## 4. Constitution & Invariant Checks
   - [ ] Respects database pooler requirements.
   - [ ] Respects zero-disk file storage (in-memory streams).
   - [ ] Respects scraper/API rate limits & concurrency pools.
   - [ ] Respects ATS submission safety gate (conditional POST vs manual apply fallback).

   ## 5. Acceptance Criteria
   - Concrete, testable conditions for declaring the feature complete.
   - Test coverage expectations (unit tests, mocks, lint/format).
   ```

4. **Review with User**:
   - Confirm user alignment on the specification before progressing to `/spec-plan`.
