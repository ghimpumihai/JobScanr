# Feature Specification: SvelteKit Application Scaffold & Editorial Navigation

**Feature Slug**: `web-scaffold-navigation`  
**Issue Reference**: #46  
**Status**: Converged (2026-10-16)  
**Created**: 2026-10-16  

---

## 1. Problem Statement & User Value

### 1.1 Problem Statement
JobScanr's backend pipeline discovers early-career software engineering roles from 380+ direct company ATS career boards (Greenhouse, Lever, Ashby, Workday, SmartRecruiters, Teamtailor) and delivers daily 06:00 UTC digests via email. However, candidates lack a dedicated web interface to:
1. Review and batch-queue matches discovered by the scraper.
2. Audit application submission statuses and inspect/edit CV-grounded screening answers before dispatch.
3. Manage their stored CV document and calibrate search filters without manually updating raw JSON files.

Past mockup attempts fell into common traps: over-engineered "cartographic radar / NASA terminal" jargon, generic bubbly SaaS pill cards, juvenile emojis, and sparse 4-tab layouts with 70% dead whitespace.

### 1.2 User Value
- **Seamless Continuity**: Transitioning from the daily 06:00 UTC email digest into the web app feels like an immediate, calm extension of the email ("Editorial Digest" aesthetic).
- **High-Density, Zero-Fluff Control**: Fast, scan-friendly tables and lists with no fake telemetry widgets or marketing hype.
- **Light Mode by Default**: Crisp, high-contrast Slate design with an accessible, opt-in dark mode toggle.
- **Strict Human-in-the-Loop Safety**: Candidates retain 100% authority to inspect, edit, and sign off on screening answers before any API dispatch.

---

## 2. Scope & Boundaries

### 2.1 In Scope
1. **SvelteKit Application Scaffold (`web/`)**:
   - Modern SvelteKit project initialized with Tailwind CSS and TypeScript in `web/`.
   - Reusable layout shell (`src/routes/+layout.svelte`) featuring:
     - Header brand: `JobScanr` + `Europe Engineering Feed`.
     - 3 primary navigation tabs: `Matches (4)`, `Applications (3)`, `Profile & Settings`.
     - Header actions: Theme toggle (Light by default, opt-in dark mode via `data-theme="dark"`) and user avatar initials.
     - Clean SVG icons throughout (zero emoji dependencies).
2. **Three Core Application Routes**:
   - **`/matches` (Daily Matches Feed)**:
     - 3-segment telemetry summary strip (`Feeds checked`, `Daily scan completed`, `Matching roles`).
     - Daily matching roles stream with salary badges, ATS platform tags, match scores, and direct action triggers (`Review & Queue →` for Greenhouse/Lever/Ashby; `Apply Direct ↗` for Workday).
     - Batch action header button (`Queue All Direct (3) →`).
   - **`/applications` (Application Audit Tracker)**:
     - Real-time submission status table (`Role & Company`, `Platform`, `Status`, `Submitted / Scheduled`, `Action`).
     - Semantic status badges: `Submitted` (emerald), `Needs Review` (calm amber badge with indicator dot), `Queued` (slate), `Manual Apply` (neutral).
     - Accessible slide-over Review Drawer (`role="dialog"`, `aria-modal="true"`, `Escape` listener) for inspecting audit grounding, editing screening answers, and confirming submission.
   - **`/settings` (Unified Profile & Preferences)**:
     - CV document card (`stefan_ghimpu_cv_2026.pdf`, 142 KB, Supabase Secure Storage) with high-contrast `Download CV` and `Replace CV` buttons.
     - Candidate identity inputs (Full Name, Contact Email).
     - Target Seniority filter with all 8 engineering levels (*Internship / Working Student*, *Graduate / New Grad*, *Entry Level 0-1 yrs*, *Junior 1-2 yrs*, *Associate 2-3 yrs*, *Mid-Level 3-5 yrs*, *Senior 5-8 yrs*, *Lead / Principal 8+ yrs*).
     - Interactive tag clouds for Preferred Locations and Excluded Keywords (negative filter) with accessible SVG removal buttons.
     - Work authorization default input.
     - Save Preferences button with feedback toast.
   - **Route Alias**:
     - `/profile` redirects cleanly to `/settings` to eliminate fragmented, empty pages.
3. **Authentication & Session Guarding (`@supabase/ssr`)**:
   - Cookie-based Supabase session handling in `src/hooks.server.ts`.
   - Protected routes (`/matches`, `/applications`, `/settings`) redirect unauthenticated requests to `/login`.
   - Clean `/login` page supporting Magic Link and 6-digit email OTP sign-in.
4. **Data Contracts & TypeScript Interfaces**:
   - Strong TypeScript definitions matching backend schema: `User`, `JobPosting`, `ApplicationRecord`, `ApplicationEvent`, `ScreeningQuestion`.
   - Lightweight API and Supabase client helpers in `src/lib/`.

### 2.2 Out of Scope (Ponytail Pushback / Code Never Written)
- **Client-side Resume Re-compiler / Canvas Editor**: Dropped. Authentic uploaded PDFs/DOCXs are stored in Supabase Storage and parsed server-side. No Canva-style drag-and-drop resume builder.
- **Complex Telemetry Graphics & Heavy Chart Libraries**: Dropped. No D3, Chart.js, or canvas radar grids. Clean HTML/CSS tabular strips achieve higher legibility with zero bundle bloat.
- **Emoji Packs / Heavy Icon Font Bundles**: Dropped. Pure self-contained inline SVG icons.
- **Autonomous Auto-Submit Bot**: Prohibited by project constitution (§1.5). All submissions require explicit candidate sign-off or pre-configured deterministic screening defaults.

---

## 3. Acceptance Criteria

1. **Scaffold & Build**:
   - SvelteKit application builds cleanly (`npm run build` and `npm run check` succeed with zero TypeScript errors).
2. **Navigation & Theming**:
   - Layout renders light mode by default.
   - Clicking the theme toggle switches to dark mode (`data-theme="dark"`) and preserves high contrast across all text and badges (WCAG AA compliant).
   - Zero emojis rendered in the UI; all icons are clean SVGs.
3. **Route Protection**:
   - Direct navigation to `/matches`, `/applications`, or `/settings` without an active session redirects to `/login`.
   - Authenticated sessions access all routes seamlessly.
4. **Interactive Mock Data Parity**:
   - All 3 routes render mock state matching `web_mockup_artifact.html`.
   - Drawer opens on row click / button trigger and closes on `Escape` or backdrop click.
   - Seniority chips toggle `aria-pressed` states interactively.
   - Location and keyword tag clouds support interactive removal.
