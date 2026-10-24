<script lang="ts">
  import '../app.css';
  import { page, navigating } from '$app/stores';
  import Icon from '$lib/components/Icon.svelte';
  import type { Snippet } from 'svelte';
  import type { LayoutData } from './$types';

  let { children, data }: { children: Snippet; data: LayoutData } = $props();

  let isDark = $state(
    typeof document !== 'undefined'
      ? document.documentElement.getAttribute('data-theme') === 'dark'
      : false
  );

  // Synchronize theme state with document and localStorage
  $effect(() => {
    if (typeof window !== 'undefined') {
      const stored = localStorage.getItem('jobscanr-theme');
      const docDark = document.documentElement.getAttribute('data-theme') === 'dark';
      if (stored === 'dark' || docDark) {
        isDark = true;
        document.documentElement.setAttribute('data-theme', 'dark');
      } else {
        isDark = false;
        document.documentElement.removeAttribute('data-theme');
      }
    }
  });

  function toggleTheme() {
    isDark = !isDark;
    if (isDark) {
      document.documentElement.setAttribute('data-theme', 'dark');
      localStorage.setItem('jobscanr-theme', 'dark');
    } else {
      document.documentElement.removeAttribute('data-theme');
      localStorage.setItem('jobscanr-theme', 'light');
    }
  }

  function isActive(path: string): boolean {
    return $page.url.pathname.startsWith(path);
  }

  let isLoginPage = $derived($page.url.pathname === '/login');

  let userInitials = $derived.by(() => {
    if (data.user?.email) {
      return data.user.email.slice(0, 2).toUpperCase();
    }
    return 'SG';
  });
</script>

<div class="min-h-screen bg-page text-content-primary">
  {#if $navigating}
    <div
      class="fixed top-0 left-0 right-0 z-50 h-0.5 overflow-hidden bg-brand-blue/20"
      role="progressbar"
      aria-label="Loading page navigation"
    >
      <div class="h-full w-full bg-brand-blue animate-pulse"></div>
    </div>
  {/if}

  <div class="mx-auto max-w-5xl px-4 py-8 sm:px-6 lg:px-8">
    <!-- Header Navigation -->
    <header class="mb-8 border-b border-border-main pb-5">
      <div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <!-- Top bar: Logo on left, Actions on right (same line on mobile) -->
        <div class="flex items-center justify-between sm:contents">
          <div class="flex items-center gap-3">
            <a href="/matches" class="text-2xl font-bold tracking-tight text-content-primary hover:opacity-90">
              JobScanr
            </a>
          </div>

          <!-- Actions: same line as logo on mobile, right-aligned on desktop -->
          <div class="flex items-center gap-2.5 sm:order-last">
            <button
              type="button"
              class="inline-flex min-h-[36px] min-w-[36px] sm:min-h-0 sm:min-w-0 items-center justify-center gap-1.5 rounded-md border border-border-strong bg-card p-2 sm:px-2.5 sm:py-1.5 text-xs text-content-secondary shadow-sm transition-colors hover:bg-hover hover:text-content-primary"
              onclick={toggleTheme}
              title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
              aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {#if isDark}
                <Icon name="sun" size={14} />
              {:else}
                <Icon name="moon" size={14} />
              {/if}
            </button>

            {#if !isLoginPage}
              <div
                class="flex h-8 w-8 items-center justify-center rounded-full bg-brand-blue text-xs font-bold text-white shadow-sm"
                title={data.user?.email || 'stefan@example.com'}
              >
                {userInitials}
              </div>
              <a
                href="/login?logout=true"
                class="btn-secondary !py-1.5 !text-xs"
                title="Sign out of JobScanr"
              >
                Sign Out
              </a>
            {:else}
              <a
                href="/matches?demo=true"
                class="btn-action !py-1.5 !text-xs"
                title="Explore Demo Mode"
              >
                Demo Mode
                <Icon name="arrow-right" size={11} />
              </a>
            {/if}
          </div>
        </div>

        {#if !isLoginPage}
          <nav class="flex w-full flex-wrap gap-1 rounded-lg border border-border-main bg-subtle p-1 sm:w-auto" aria-label="Main Navigation">
            <a
              href="/matches"
              class="flex flex-1 sm:flex-initial min-h-[36px] sm:min-h-0 items-center justify-center rounded-md px-3.5 py-2 sm:py-1.5 text-xs font-semibold transition-all {isActive('/matches')
                ? 'bg-card text-content-primary shadow-sm'
                : 'text-content-muted hover:text-content-primary'}"
            >
              Matches (4)
            </a>
            <a
              href="/applications"
              class="flex flex-1 sm:flex-initial min-h-[36px] sm:min-h-0 items-center justify-center rounded-md px-3.5 py-2 sm:py-1.5 text-xs font-semibold transition-all {isActive('/applications')
                ? 'bg-card text-content-primary shadow-sm'
                : 'text-content-muted hover:text-content-primary'}"
            >
              Applications (3)
            </a>
            <a
              href="/settings"
              class="flex flex-1 sm:flex-initial min-h-[36px] sm:min-h-0 items-center justify-center rounded-md px-3.5 py-2 sm:py-1.5 text-xs font-semibold transition-all {isActive('/settings')
                ? 'bg-card text-content-primary shadow-sm'
                : 'text-content-muted hover:text-content-primary'}"
            >
              Profile &amp; Settings
            </a>
          </nav>
        {/if}
      </div>
    </header>

    <!-- Page Content -->
    <main>
      {@render children()}
    </main>
  </div>
</div>
