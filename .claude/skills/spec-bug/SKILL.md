---
name: spec-bug
description: Assess, reproduce, fix, and verify bugs in .specify/bugs/<slug>/ with structured root-cause logging.
---

# Spec-Driven Development: Bug Fix & Assessment

Use this skill when diagnosing, fixing, and verifying bugs following Spec Kit extension standards.

## Workflow

1. **Identify Bug Slug**:
   - Determine or prompt for a concise bug slug (e.g. `ashby-null-throttle`, `pooler-connection-timeout`).
   - Bug directory: `.specify/bugs/<slug>/`.

2. **Assess & Reproduce (`.specify/bugs/<slug>/assessment.md`)**:
   Document the bug assessment:
   ```markdown
   # Bug Assessment: <Title>

   **Bug Slug**: `<slug>`  
   **Status**: Investigating | Root Cause Identified | Fixed | Verified  
   **Issue Reference**: #<number> (if applicable)  

   ## 1. Symptom & Reported Behavior
   - Observed error, exception traceback, or incorrect behavior.
   - Affected platforms or components.

   ## 2. Minimal Reproduction
   - Step-by-step reproduction instructions or standalone test snippet.

   ## 3. Root Cause Analysis
   - Grep all callers and consumers of the failing function.
   - Explain the technical root cause (why the failure occurred).

   ## 4. Minimal Proposed Fix
   - Smallest complete change addressing the root cause.
   - Adhere to Ponytail principles: fix root cause once in shared code.
   ```

3. **Implement Root Cause Patch**:
   - Apply the targeted fix.
   - Maintain existing error handling and validation.

4. **Verify & Write Regression Test**:
   - Add a targeted regression test in `tests/` reproducing the exact failure scenario.
   - Run tests:
     ```bash
     python -m pytest tests/test_<module>.py
     ```

5. **Log Verdict**:
   - Update `.specify/bugs/<slug>/assessment.md` with:
     ```markdown
     ## 5. Verification Verdict
     - **Result**: Verified | Partial | Failed
     - **Regression Test**: `tests/test_<module>.py::<test_name>`
     ```
