# Implementation Tasks: SvelteKit Application Scaffold & Editorial Navigation

**Feature Slug**: `web-scaffold-navigation`  
**Plan Reference**: [.specify/specs/web-scaffold-navigation/plan.md](./plan.md)  
**Spec Reference**: [.specify/specs/web-scaffold-navigation/spec.md](./spec.md)  
**Status**: Completed  

---

## Phase 1: Project Scaffolding & Configuration
- [x] Task 1.1: Initialize SvelteKit project in `web/` with TypeScript, Vite, and Tailwind CSS (`web/package.json`, `web/svelte.config.js`, `web/vite.config.ts`, `web/tsconfig.json`, `web/tailwind.config.ts`).
- [x] Task 1.2: Install `@supabase/ssr` and `@supabase/supabase-js` dependencies in `web/`.
- [x] Task 1.3: Define TypeScript contracts and models matching backend schema in `web/src/lib/types/index.ts` (`JobMatch`, `ApplicationRecord`, `UserProfile`, `ATSPlatform`, `ApplicationStatus`).

## Phase 2: Design System Tokens, SVG Icons & Global Shell
- [x] Task 2.1: Configure Tailwind CSS custom properties and theme tokens matching the Editorial Digest system (`--bg-page`, `--bg-card`, `--blue-primary`, `--emerald-bg`, `--amber-bg`, etc.) in `web/src/app.css` and `web/tailwind.config.ts`.
- [x] Task 2.2: Implement typed inline SVG icon component `web/src/lib/components/Icon.svelte` (`sun`, `moon`, `external-link`, `close`, `document`, `download`, `status-dot`, `arrow-right`).
- [x] Task 2.3: Build root application shell `web/src/routes/+layout.svelte` with brand header, 3-tab navigation bar (`Matches`, `Applications`, `Profile & Settings`), light-mode default, dark mode toggle (`data-theme="dark"`), and user avatar initials.

## Phase 3: Supabase Auth & SSR Session Guarding
- [x] Task 3.1: Configure browser and server Supabase client factories in `web/src/lib/supabase/client.ts` and `web/src/lib/supabase/server.ts`.
- [x] Task 3.2: Implement cookie-based authentication hook in `web/src/hooks.server.ts` guarding protected routes (`/matches`, `/applications`, `/settings`) with a 303 redirect to `/login`.
- [x] Task 3.3: Implement sign-in route `web/src/routes/(auth)/login/+page.svelte` and `web/src/routes/(auth)/login/+page.server.ts` supporting Magic Link and 6-digit OTP email login.

## Phase 4: Core Application Routes & Interactivity
- [x] Task 4.1: Implement `/matches` feed route in `web/src/routes/(app)/matches/+page.svelte` featuring the 3-segment telemetry heartbeat strip, daily matching jobs stream, salary tags, ATS badges, batch queue action, and direct career links.
- [x] Task 4.2: Implement `/applications` audit route in `web/src/routes/(app)/applications/+page.svelte` featuring the real-time status table, semantic status badges, and slide-over review drawer (`web/src/lib/components/ReviewDrawer.svelte`) with `role="dialog"`, `aria-modal="true"`, and `Escape` key listener.
- [x] Task 4.3: Implement `/settings` unified control route in `web/src/routes/(app)/settings/+page.svelte` featuring the CV document card with high-contrast download/replace actions, candidate contact inputs, 8-tier seniority filter chips, interactive location and keyword tag clouds, and work authorization defaults.
- [x] Task 4.4: Add route alias `web/src/routes/(app)/profile/+page.server.ts` issuing a permanent 301 redirect to `/settings`.

## Phase 5: Verification & Build Validation
- [x] Task 5.1: Run `npm run check` (TypeScript and Svelte rune check) in `web/` with zero errors.
- [x] Task 5.2: Run `npm run build` in `web/` to confirm production asset compilation.
- [x] Task 5.3: Verify Python backend test suite (`python -m pytest tests/`), `ruff check .`, and `mypy` to confirm zero regressions across the codebase.
