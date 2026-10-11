---
name: spec-implement
description: Execute implementation step-by-step against .specify/specs/<slug>/tasks.md, updating checkboxes as tasks complete.
---

# Spec-Driven Development: Implement

Use this skill to execute tasks defined in `.specify/specs/<slug>/tasks.md`.

## Workflow

1. **Locate and Review Artifacts**:
   - Read `.specify/specs/<slug>/tasks.md`, `.specify/specs/<slug>/plan.md`, and `.specify/specs/<slug>/spec.md`.
   - Identify the next uncompleted task (`- [ ]`).

2. **Execute Incrementally**:
   - Implement the code changes required for the current task.
   - Adhere strictly to the design boundaries specified in `plan.md` and repository standards in `.specify/constitution.md`.
   - Write or update corresponding unit tests alongside implementation.

3. **Verify Each Step**:
   - Run tests for the touched module immediately:
     ```bash
     python -m pytest tests/test_<module>.py
     ```
   - Run quick lint check:
     ```bash
     ruff check <touched_files>
     ```

4. **Update Progress in `tasks.md`**:
   - Mark the completed item as `- [x]` in `.specify/specs/<slug>/tasks.md`.

5. **Repeat or Transition**:
   - Proceed to the next task until all tasks are marked `- [x]`.
   - Once all tasks are complete, invoke `/spec-converge`.
