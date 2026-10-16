# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack
SvelteKit, Tailwind CSS, TypeScript, @supabase/ssr, Supabase PostgreSQL, ReportLab

## Users
Early-career and mid-level software engineers across Europe (UK, EU, Remote EU) actively searching for verified engineering roles without aggregator spam or ghost jobs.

## Product Purpose
JobScanr automates the discovery, matching, screening question drafting, and application submission for engineering roles from 380+ direct company ATS boards (Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Teamtailor), providing candidates with daily curated digests and a high-control application audit dashboard.

## Positioning
Unlike broad aggregators (LinkedIn, Indeed) that surface stale, duplicate, or ghost postings, JobScanr scans verified first-party career feeds directly at 06:00 UTC daily, parses ATS-specific question schemas, pre-drafts CV-grounded answers without hallucinations, and gives users transparent human-in-the-loop control with zero autonomous blind submits.

## Operating Context
- Daily cadence: Batch scraping and scoring completes at 06:00 UTC; users receive an editorial HTML email digest on mobile/desktop and transition into the web portal for in-depth review and action.
- High-trust boundary: Job application submission directly impacts a candidate's career reputation. The system operates strictly in 'approval_required' mode by default, requiring explicit candidate sign-off on custom essay answers and screening answers before API dispatch.
- ATS Variety: Direct conditional HTTP POST for Greenhouse and Lever; guided 'manual_apply' with 1-click clipboard helpers for Cloudflare Turnstile or auth-walled portals (Ashby, Workday, SmartRecruiters, Teamtailor).

## Capabilities and Constraints
- Direct ATS scraping across 3,600+ companies (Greenhouse, Lever, SmartRecruiters, Teamtailor, Workday, Ashby) with rate limiters and pacing locks.
- Supabase Auth (Magic Link & 6-digit email OTP) with SSR cookie session validation.
- Supabase PostgreSQL with Row Level Security (RLS) ensuring strict user data isolation.
- CV PDF/DOCX upload with document security validation (MIME sniffing, size caps) and ReportLab test PDF generator.
- Reactive client-side single-column ATS resume preview.
- Groq Llama 3.3 LLM question answering with negative anti-hallucination prompts strictly grounded in CV facts, with exponential backoff and empty-fallback to manual review.
- Emergency user kill switch to instantly freeze background worker processing of queued applications.

## Brand Commitments
- Visual identity: "Editorial Digest" — Exact visual continuity with the daily 06:00 UTC email digest (`jobs/notify.py`). Clean, high-signal, calm executive utility with zero visual clutter.
- Structural geometry: Standard subtle rounded cards (border-radius 6px–8px), calibrated 1px borders (`#e2e8f0`), clear horizontal dividers (`#f1f5f9`), and compact tabular density.
- Color system:
  - Canvas grounds: Neutral slate background (`#f1f5f9` / `#f8fafc`) and crisp white card containers (`#ffffff`).
  - Primary brand & action blue: `#0a66c2` for titles, links, and pill action buttons (`border-radius: 20px`).
  - Signal Emerald: `#ecfdf5` background with `#047857` text for compensation tags, verified feeds, and active status (`● Radar Active`).
  - Signal Slate: `#f1f5f9` background with `#475569` text for ATS platform tags (`via Greenhouse`, `via Lever`).
  - Amber Warning: `#fffbeb` background with `#92400e` text for review actions and screening prompts.
  - High-contrast Slate text: Slate-900 (`#0f172a`) for titles/headings, Slate-700 (`#334155`) for subtitles/meta, Slate-600 (`#475569`) for body text, and Slate-500 (`#64748b`) for subtle captions.
- Typography System:
  - Clean font stack matching the email: `-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif`.
  - Tabular monospace font (`ui-monospace, SFMono-Regular, Menlo, monospace`) reserved strictly for timestamps, salary amounts, and attempt tokens.

## Evidence on Hand
- Email digest HTML template (`jobs/notify.py`) containing the exact design language, badge styles, telemetry status cards, and layout rhythm.
- Issue #46: SvelteKit + Tailwind CSS application scaffold, routing (`/matches`, `/applications`, `/profile`, `/settings`), and Supabase Auth.
- Issue #47: CV JSON editor, ATS preview, search filters, and auto-apply controls.
- Issue #48: Applications audit dashboard, status tabs, screening review drawer, and emergency kill switch.
- Production and staging Supabase database schema (`db/schema.sql`).
- Grounded LLM question answering spike (`docs/llm_question_answering_spike.md`).
- ATS unauthenticated submission spike (`docs/ats_submission_spike.md`).

## Product Principles
1. Transparent Human-in-the-Loop Control: Automation handles the tedious extraction and drafting, but candidates retain absolute authority over what is submitted in their name.
2. Verified Ground Truth: Zero hallucinations in CV representation, zero ghost jobs from aggregators, direct ATS source links always accessible.
3. Focused Editorial Calm: UI mirrors the clean, high-signal email digest—no flashy animations or gamified noise; just fast scanning, clear telemetry, and confident execution.
4. Fail-Safe Resiliency: If bot protections, rate limits, or schema mismatches occur, the system fails gracefully into guided manual apply rather than dropping or corrupting submissions.

## Accessibility & Inclusion
- WCAG 2.1 AA compliant contrast ratios across Slate text and colored badges.
- Full keyboard navigation for modal drawers, tab bars, and data tables.
- Accessible form validation states with explicit aria-live announcements for ATS parsing feedback and queue updates.
