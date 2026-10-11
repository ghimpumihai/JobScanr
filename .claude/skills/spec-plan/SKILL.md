---
name: spec-plan
description: Generate a technical architecture implementation plan in .specify/specs/<slug>/plan.md based on an approved spec.
---

# Spec-Driven Development: Plan

Use this skill after `/spec-specify` to formulate the technical architecture, data flow, component boundaries, and dependency ordering before coding.

## Workflow

1. **Verify Existing Specification**:
   - Locate and read `.specify/specs/<slug>/spec.md`. Ensure requirements and acceptance criteria are unambiguous.
   - Verify alignment with `.specify/constitution.md`.

2. **Draft or Update `.specify/specs/<slug>/plan.md`**:
   The plan artifact must contain:
   ```markdown
   # Technical Implementation Plan: <Title>

   **Feature Slug**: `<slug>`  
   **Spec Reference**: [.specify/specs/<slug>/spec.md](./spec.md)  
   **Status**: Draft | Approved | Executing | Converged  

   ## 1. Architectural Strategy & Design Trade-offs
   - Summary of technical approach.
   - Comparison of alternatives considered and reasons for the chosen pattern.
   - Minimizing new code (Ponytail principles: reuse existing modules, standard library, or existing patterns).

   ## 2. Component Boundaries & Critical Files
   - List every file created or modified:
     - New modules (e.g. `jobs/apply/runner.py`)
     - Modified modules (e.g. `db/queries.py`)
     - Database migrations / schemas (e.g. `db/schema.sql`)
     - Test files (e.g. `tests/test_runner.py`)

   ## 3. Data Flow & Interfaces
   - Types, data contracts, and signatures (`dataclass`, `TypedDict`, `pydantic`, or DB schemas).
   - Error states, exception hierarchies, and recovery mechanisms.

   ## 4. Testing & Verification Strategy
   - Mocking strategy (e.g. `httpx.MockTransport`, mock DB pools).
   - Edge cases to cover (transient network drops, 429 rate limits, partial responses, invalid payloads).
   - Verification commands:
     ```bash
     ruff check .
     ruff format --check .
     mypy <modules>
     python -m pytest tests/test_<feature>.py
     ```

   ## 5. Risk Assessment & Safety Circuit Breakers
   - Call out failure modes, potential database locks, external API throttles, and safeguards.
   ```

3. **Present Plan for Review**:
   - Present the architecture and file impact to the developer before proceeding to `/spec-tasks`.
