---
name: spec-converge
description: Audit implementation against spec, run quality verification gates, and confirm convergence status.
---

# Spec-Driven Development: Converge

Use this skill after `/spec-implement` to verify that the implementation completely satisfies the specification and repository standards, declaring convergence.

## Workflow

1. **Verify Implementation Against Spec**:
   - Re-read `.specify/specs/<slug>/spec.md` and `.specify/specs/<slug>/tasks.md`.
   - Confirm all acceptance criteria in `spec.md` have been met.
   - Confirm all tasks in `tasks.md` are marked `- [x]`.

2. **Execute Full Quality Verification Gates**:
   Run the full verification suite in order:
   ```bash
   # 1. Lint check
   ruff check .

   # 2. Format check
   ruff format --check .

   # 3. Static type check
   mypy models.py config.py scrapers/

   # 4. Catalog schema validation
   python -m scripts.validate_seed_schema

   # 5. Full test suite
   python -m pytest tests/
   ```

3. **Check Invariant Compliance**:
   - Check compliance with `.specify/constitution.md` (database pooler usage, zero-disk PDF policy, rate limits, no live scraping in unit tests).

4. **Update Artifact Status**:
   - Set status in `.specify/specs/<slug>/spec.md` and `plan.md` to:
     ```markdown
     **Status**: Converged (YYYY-MM-DD)
     ```

5. **Summarize Deliverable**:
   - Output a concise convergence summary:
     - Implemented modules and lines changed.
     - Test coverage and execution time.
     - Any trade-offs, shortcuts, or future enhancements noted.
