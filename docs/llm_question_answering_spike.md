# Spike: LLM-Grounded Open-Ended Question Drafting & Human-in-the-Loop Fallback

> **Issue Reference**: Linked to Issue #49 (ATS Submission Spike) & Issue #51 (Greenhouse/Lever Submitters)  
> **Status**: INVESTIGATED & ARCHITECTED  
> **Target Downstream**: Issue #48 (Review Drawer UI) & Issue #53 (Application Queue Worker)

---

## 1. Problem Statement & Scope

During automated job application processing on Greenhouse and Lever, candidate submissions encounter two categories of screening questions:
1. **Deterministic / Closed Questions**: Work authorization, visa sponsorship, years of experience, notice period, location.
   - Handled directly by `user.screening_defaults` with 100% confidence.
2. **Open-Ended / Essay Questions**:
   - Examples: *"Describe a complex distributed systems bug you resolved"*, *"Why are you interested in this role at Acme?"*, *"Summarize your experience with Kubernetes in production"*.
   - **Problem**: These cannot be answered by static scalar values. Currently, they either block automation or force immediate manual entry.
   - **Objective**: Use a lightweight, fast LLM (Groq: Llama 3.3 / GPT-OSS) to pre-draft answers **strictly grounded in the candidate's CV**, with robust rate-limit retries (3 attempts), automatic fallback to `needs_review`, and human-in-the-loop approval before submission.

---

## 2. Risk Analysis & Grounding Strategy

### 2.1 The Hallucination Hazard
If an unconstrained LLM generates answers to technical screening questions, it will invent tools, metrics, and past projects not present in the candidate's background. If submitted to employers:
- Recruiters catch inconsistencies during phone screens or background checks.
- The candidate is permanently disqualified and flagged for fraudulent application.

### 2.2 Strict Zero-Hallucination Guardrails
The system prompt must enforce negative constraints:
1. **Facts Boundary**: Only reference employers, titles, tools, and achievements explicitly documented in the candidate's `resume_data` JSON.
2. **Transferable Baseline**: If the CV lacks direct experience with a queried technology, the model must state the candidate's actual baseline honestly (e.g. *"While my core container orchestration experience is in Docker and ECS rather than Kubernetes, I have..."*) rather than fabricating Kubernetes projects.
3. **No Metric Invention**: Never fabricate percentages, dollar amounts, or team sizes not found in the CV.
4. **Length and Tone**: Direct, professional, first-person ("I"). Answer the core prompt in the very first sentence without preamble ("As a software engineer...", "I am thrilled to apply...").

---

## 3. Rate Limiting, Retries, and Circuit Breakers

### 3.1 Groq API Limits
- Free / Developer tiers on Groq enforce Requests Per Minute (RPM) and Tokens Per Minute (TPM) caps (e.g., 30 RPM, 6,000 TPM).
- An application burst with 3–5 open questions can quickly trigger HTTP 429 (`Too Many Requests`).

### 3.2 3-Attempt Exponential Backoff Spec
1. **Attempt 1**: Initial inference request (timeout: 10s).
2. **On HTTP 429**:
   - Read `Retry-After` header if provided by Groq.
   - If missing, apply linear/exponential backoff: `delay = 2.0 * attempt` (2s, 4s).
   - Retry up to **3 attempts total**.
3. **Exhaustion / Failure**:
   - If all 3 attempts fail, or if Groq returns 5xx/network errors:
   - **Do NOT fail the pipeline or abort the application.**
   - Mark `draft_status = "unanswered"` with `reason = "rate_limit_exceeded"`.
   - Transition the application to **`needs_review`**.
   - The user will see the empty question in the Review Drawer (Issue #48) to answer manually.

---

## 4. State Machine & Human-in-the-Loop Integration

```text
[Question Schema Extracted]
             │
             ├──> Deterministic Question ──> Map from user.screening_defaults (100% confidence)
             │
             └──> Open-Ended / Essay Question
                       │
                       ▼
             [LLM Drafting with CV Grounding]
                       │
                       ├──> 429 Rate Limit ──> [Retry 1..3 with Backoff]
                       │                              │
                       │                              └──> 3 Failures ──> [needs_review (empty)]
                       │
                       ├──> Draft Succeeded
                       │         │
                       │         ▼
                       │    [Store in applications.custom_answers]
                       │    [Transition to needs_review]
                       │
                       ▼
             [Issue #48: Screening Review Drawer]
                       │
                       ├──> User reviews / edits drafted answers
                       └──> User clicks "Approve & Submit"
                                 │
                                 ▼
                       [Transition to queued for Issue #53 Worker]
```

### 4.1 Golden Rule: No Autonomous Blind Submit for Essays
Even when the LLM successfully generates a draft, the application **must pause at `needs_review`**. The candidate must review and approve what is submitted on their behalf.

---

## 5. Data Schema Contract

### In `applications` Table:
```json
{
  "custom_answers": {
    "question_10482": {
      "question_text": "Describe your experience with async Python.",
      "type": "textarea",
      "required": true,
      "max_length": 1000,
      "draft_answer": "At Acme Corp, I designed and maintained asyncio pipelines handling 50k events/sec...",
      "draft_status": "generated",
      "user_edited": false,
      "approved": false
    }
  }
}
```

---

## 6. Downstream Roadmap Impact
- **Issue #49** (Spike): Identified question schemas on Greenhouse (`question_{id}`) and Lever (`cards[{id}]`).
- **New Issue #54**: Implementation of `jobs/apply/llm_answers.py` (Groq client, prompt engineering, retry circuit breaker).
- **Issue #51**: Integrates `draft_open_question_answer` into `BaseSubmitter`.
- **Issue #48**: Renders the generated drafts in the frontend Review Drawer for approval.
