---
name: spec-tasks
description: Break down an architectural plan into an ordered, testable checklist in .specify/specs/<slug>/tasks.md.
---

# Spec-Driven Development: Tasks

Use this skill after `/spec-plan` to decompose the technical plan into discrete, bite-sized, dependency-ordered tasks with clear verification checkpoints.

## Workflow

1. **Verify Plan & Spec**:
   - Locate and read `.specify/specs/<slug>/plan.md` and `.specify/specs/<slug>/spec.md`.

2. **Draft or Update `.specify/specs/<slug>/tasks.md`**:
   The task list must contain:
   ```markdown
   # Implementation Tasks: <Title>

   **Feature Slug**: `<slug>`  
   **Plan Reference**: [.specify/specs/<slug>/plan.md](./plan.md)  
   **Status**: Ready | In Progress | Completed  

   ## Phase 1: Models, Schemas & Core Data Contracts
   - [ ] Task 1.1: Define data types / schema changes in `models.py` or `db/schema.sql`.
   - [ ] Task 1.2: Add unit tests / assertions for schema validity.

   ## Phase 2: Core Business Logic & Engine
   - [ ] Task 2.1: Implement core functions / classes in target module.
   - [ ] Task 2.2: Implement error handling, timeouts, and circuit breakers.

   ## Phase 3: Integration & Callers
   - [ ] Task 3.1: Wire callers / scripts / pipelines.
   - [ ] Task 3.2: Add CLI arguments or configuration settings if applicable.

   ## Phase 4: Verification & Test Suite
   - [ ] Task 4.1: Write comprehensive unit tests with mock transports.
   - [ ] Task 4.2: Run `ruff check .`, `ruff format --check .`, and `mypy`.
   - [ ] Task 4.3: Execute full test suite `python -m pytest tests/`.
   ```

3. **Task Rules**:
   - Tasks must be ordered chronologically by dependency.
   - Each task must be verifiable independently.
   - Keep tasks scoped so any single task can be implemented in a single turn without context exhaustion.
