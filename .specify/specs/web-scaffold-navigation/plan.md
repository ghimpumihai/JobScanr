# Technical Implementation Plan: SvelteKit Application Scaffold & Editorial Navigation

**Feature Slug**: `web-scaffold-navigation`  
**Spec Reference**: [.specify/specs/web-scaffold-navigation/spec.md](./spec.md)  
**Status**: Converged (2026-10-16)  
**Issue Reference**: #46  

---

## 1. Architectural Strategy & Design Trade-offs

### 1.1 Technical Approach
The frontend lives in a dedicated `web/` directory at the repository root, powered by **SvelteKit + Svelte 5 (Runes) + Tailwind CSS + TypeScript + `@supabase/ssr`**.

Visual and behavioral identity is locked to the **"Editorial Digest"** system verified in `web_mockup_artifact.html`:
- Slate-50 background (`#f8fafc`) with clean bordered white cards (`#ffffff`, `border: 1px solid #e2e8f0`, `border-radius: 8px`).
- Light mode by default; manual dark mode override via `:root[data-theme="dark"]` with zero contrast degradation.
- Zero emojis; all visual indicators and controls are self-contained, typed inline SVG components.
- Crisp rectangular action buttons (`border-radius: 6px; font-weight: 600; font-size: 13px; letter-spacing: -0.01em`).
- Three high-density primary views (`/matches`, `/applications`, `/settings`), with `/profile` cleanly aliased to `/settings` to eliminate empty dead space.

```text
[ Browser Client ]
       │
       │ HTTP Request + Auth Cookie
       ▼
[ SvelteKit Server (web/src/hooks.server.ts) ]
       │
       ├── @supabase/ssr creates server client & validates session
       ├── Route Guard: Protected route & no session? ──► Redirect to /login
       ▼
[ SvelteKit Page Component (routes/(app)/...) ]
       │
       ├── Svelte 5 Runes ($state, $derived, $props)
       ├── Reusable Components (ReviewDrawer, TelemetryStrip, Icon)
       ▼
[ Supabase PostgreSQL + Storage via RLS (Anon Key + User JWT) ]
```

### 1.2 Minimizing New Code (Ponytail Principles)
1. **No External Icon Libraries**: Dropped `lucide-svelte` / `font-awesome` / `@heroicons`. A single typed `<Icon name="..." />` component with 8 raw SVG glyphs satisfies all iconography with zero dependency weight.
2. **No External State Libraries**: Dropped Redux/Zustand/Pinia. Svelte 5 universal reactivity runes (`$state`) and SvelteKit route `data` provide all required state.
3. **No Heavy Component Frameworks**: Dropped Radix/Shadcn/Skeleton wrappers. Native semantic HTML (`<dialog>`, `<button>`, `<input>`, `<table>`) styled with Tailwind provides smaller bundles and cleaner accessibility.
4. **No ReportLab or Client Resume Builder**: Dropped canvas/ReportLab code. Resumes are authentic user PDF/DOCX files stored in Supabase Storage and retrieved in-memory.

---

## 2. Component Boundaries & Critical Files

### 2.1 Scaffold & Configuration
- **`web/package.json`**: SvelteKit, Svelte 5, `@sveltejs/vite-plugin-svelte`, `@sveltejs/adapter-auto` (or `adapter-node`), `tailwindcss`, `@supabase/ssr`, `@supabase/supabase-js`, `typescript`.
- **`web/svelte.config.js`**: Standard SvelteKit configuration with Vite preprocessing.
- **`web/vite.config.ts`**: Vite configuration importing `@sveltejs/kit/vite` and Tailwind.
- **`web/tsconfig.json`**: Strict TypeScript configuration extending `.svelte-kit/tsconfig.json`.
- **`web/tailwind.config.ts`**: Custom color tokens mapped to our CSS custom properties (`--bg-page`, `--bg-card`, `--blue-primary`, `--emerald-bg`, etc.).
- **`web/src/app.html`**: HTML skeleton with light-mode default root and viewport metas.
- **`web/src/app.d.ts`**: Global type declarations including `App.Locals` for Supabase user session.

### 2.2 Server Hooks & Auth Architecture
- **`web/src/hooks.server.ts`**:
  - Initializes Supabase server client using `@supabase/ssr`.
  - Reads session from cookies and attaches `user` and `session` to `event.locals`.
  - Route guard interceptor: If path matches `/matches`, `/applications`, `/settings` and user is unauthenticated, redirects with `303` to `/login`.
- **`web/src/lib/supabase/client.ts`**: Browser client singleton for authenticated client-side operations.
- **`web/src/lib/supabase/server.ts`**: Factory for server-side Supabase client instantiation.

### 2.3 Shared UI Components
- **`web/src/lib/components/Icon.svelte`**: Typed inline SVG icon set:
  - `sun`, `moon`, `external-link`, `close`, `document`, `download`, `check`, `arrow-right`, `status-dot`.
- **`web/src/lib/components/TelemetryStrip.svelte`**: 3-segment summary card (`Feeds online`, `Scan completed`, `Matching roles`).
- **`web/src/lib/components/ReviewDrawer.svelte`**: Accessible slide-over drawer with `role="dialog"`, `aria-modal="true"`, focus containment, and `Escape` key dismissal.
- **`web/src/lib/components/Toast.svelte`**: Transient notification toast triggered by reactive state.

### 2.4 Application Routes & Layouts
- **`web/src/routes/+layout.server.ts`**: Exposes `session` and `user` to client layout context.
- **`web/src/routes/+layout.svelte`**: Global shell with brand logo, 3-tab navigation bar, theme toggle (`Light / Dark`), user avatar, and `<slot />`.
- **`web/src/routes/(auth)/login/+page.svelte`**: Minimalist, sober sign-in screen supporting Magic Link and 6-digit OTP email login.
- **`web/src/routes/(auth)/login/+page.server.ts`**: Form actions for calling `supabase.auth.signInWithOtp()`.
- **`web/src/routes/(app)/matches/+page.svelte`**: Discovered matches list, telemetry strip, batch queue action, direct career links.
- **`web/src/routes/(app)/matches/+page.server.ts`**: Loads daily matches from `user_job_matches` joined with `job_postings`.
- **`web/src/routes/(app)/applications/+page.svelte`**: Real-time audit tracker table with status badges and slide-over review drawer.
- **`web/src/routes/(app)/applications/+page.server.ts`**: Loads application records and event history from `applications`.
- **`web/src/routes/(app)/settings/+page.svelte`**: Unified CV document card, candidate identity, 8-tier seniority chips, location & keyword tag clouds, work auth defaults.
- **`web/src/routes/(app)/settings/+page.server.ts`**: Loads user preferences and handles form actions for saving search filters.
- **`web/src/routes/(app)/profile/+page.server.ts`**: Permanent 301 redirect to `/settings`.

### 2.5 Data Contracts & Types
- **`web/src/lib/types/index.ts`**:
  ```typescript
  export type ATSPlatform = 'greenhouse' | 'lever' | 'workday' | 'ashby' | 'smartrecruiters' | 'teamtailor';

  export type ApplicationStatus =
    | 'queued'
    | 'pending_approval'
    | 'submitting'
    | 'submitted'
    | 'needs_review'
    | 'failed'
    | 'manual_apply'
    | 'stale_closed';

  export interface JobMatch {
    id: number;
    title: string;
    company_name: string;
    location: string;
    compensation?: string;
    ats_platform: ATSPlatform;
    url: string;
    match_score: number;
  }

  export interface ApplicationRecord {
    id: number;
    title: string;
    company_name: string;
    location: string;
    ats_platform: ATSPlatform;
    status: ApplicationStatus;
    submitted_at?: string;
    scheduled_at?: string;
    attempt_token?: string;
    screening_question?: string;
    drafted_answer?: string;
    work_authorization?: string;
  }

  export interface UserProfile {
    id: number;
    email: string;
    full_name: string;
    resume_filename?: string;
    resume_uploaded_at?: string;
    resume_size_kb?: number;
    seniority_levels: string[];
    preferred_locations: string[];
    excluded_keywords: string[];
    work_authorization: string;
    auto_apply_mode: 'approval_required' | 'auto_submit' | 'disabled';
  }
  ```

---

## 3. Data Flow & Interfaces

### 3.1 Authentication Flow
1. User visits `/matches` (unauthenticated).
2. `hooks.server.ts` intercepts the request, notes no valid Supabase auth cookie, and issues a `303` redirect to `/login`.
3. User enters email on `/login`; server action invokes `supabase.auth.signInWithOtp({ email })`.
4. User clicks Magic Link in email or enters 6-digit OTP.
5. Supabase sets secure HTTP-only session cookies; user is redirected to `/matches`.

### 3.2 State Management with Svelte 5 Runes
- Tab navigation state: Pure URL path-based (`$page.url.pathname`).
- Theme state: Stored in `localStorage` and toggled via `document.documentElement.setAttribute('data-theme', theme)`.
- Review drawer: Reactive local rune `$state<ApplicationRecord | null>(null)`; opens on selection, closes on `Escape` or backdrop click.
- Filter chips & tag clouds: Reactive array state `$state<string[]>([...])` with live `aria-pressed` synchronization.

---

## 4. Testing & Verification Strategy

### 4.1 Verification Commands
```bash
# Frontend validation
cd web
npm run check          # TypeScript & Svelte syntax validation (svelte-check)
npm run build          # Production build check

# Root repository checks (must remain green with zero regressions)
ruff check .           # Python backend lint check
ruff format --check .  # Python formatting check
mypy models.py config.py scrapers/
python -m pytest tests/
```

### 4.2 Edge Cases & Visual Tests
- **No Active CV**: Gracefully render empty upload state if user has not yet uploaded a resume.
- **Narrow Mobile Viewports (320px–480px)**: Telemetry strip stacks vertically, table scrolls smoothly without breaking page layout.
- **Zero-Match Days**: Mirror email digest positive heartbeat telemetry card (`388 / 388 Feeds online, All systems healthy`).
- **Dark Mode Contrast**: Verify all badges and text exceed WCAG AA 4.5:1 ratio under `data-theme="dark"`.

---

## 5. Risk Assessment & Safety Circuit Breakers

1. **Database RLS Invariant (§1.1)**:
   - The SvelteKit frontend communicates with Supabase exclusively using the public `anon` key + authenticated user JWT.
   - The backend `service_role` key is never exposed to frontend code or client bundles.
2. **Submission Human-in-the-Loop (§1.5)**:
   - The UI defaults to `approval_required`.
   - The review drawer requires an explicit button click (`Approve & Submit Application →`) before any application transitions to `submitting`.
3. **No Disk Storage Invariant (§1.2)**:
   - Resume uploads stream directly from the browser to Supabase Storage `resumes/${auth.uid()}/` via signed URLs. Zero local disk caching.
