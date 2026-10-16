<script lang="ts">
  import '../app.css';
  import { page } from '$app/stores';
  import Icon from '$lib/components/Icon.svelte';
  import type { Snippet } from 'svelte';
  import type { LayoutData } from './$types';

  let { children, data }: { children: Snippet; data: LayoutData } = $props();

  let isDark = $state(false);

  // Initialize theme from document or localStorage on mount
  $effect(() => {
    if (typeof window !== 'undefined') {
      const stored = localStorage.getItem('jobscanr-theme');
      if (stored === 'dark') {
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

  let userInitials = $derived.by(() => {
    if (data.user?.email) {
      return data.user.email.slice(0, 2).toUpperCase();
    }
    return 'SG';
  });
</script>

<div class="min-h-screen bg-page text-content-primary">
  <div class="mx-auto max-w-[860px] px-4 py-6">
    <!-- Header Navigation -->
    <header class="mb-6 flex flex-col gap-3 border-b border-border-main pb-4 sm:flex-row sm:items-center sm:justify-between">
      <div class="flex items-baseline gap-2.5">
        <a href="/matches" class="text-xl font-bold tracking-tight text-content-primary hover:opacity-90">
          JobScanr
        </a>
        <span class="text-xs text-content-caption">Europe Engineering Feed</span>
      </div>

      <nav class="flex gap-1 rounded-lg border border-border-main bg-subtle p-1" aria-label="Main Navigation">
        <a
          href="/matches"
          class="rounded-md px-3.5 py-1.5 text-xs font-semibold transition-all {isActive('/matches')
            ? 'bg-card text-content-primary shadow-sm'
            : 'text-content-muted hover:text-content-primary'}"
        >
          Matches (4)
        </a>
        <a
          href="/applications"
          class="rounded-md px-3.5 py-1.5 text-xs font-semibold transition-all {isActive('/applications')
            ? 'bg-card text-content-primary shadow-sm'
            : 'text-content-muted hover:text-content-primary'}"
        >
          Applications (3)
        </a>
        <a
          href="/settings"
          class="rounded-md px-3.5 py-1.5 text-xs font-semibold transition-all {isActive('/settings')
            ? 'bg-card text-content-primary shadow-sm'
            : 'text-content-muted hover:text-content-primary'}"
        >
          Profile &amp; Settings
        </a>
      </nav>

      <div class="flex items-center gap-2.5 self-end sm:self-auto">
        <button
          type="button"
          class="inline-flex items-center gap-1.5 rounded-md border border-border-strong bg-card px-2.5 py-1.5 text-xs text-content-secondary shadow-sm transition-colors hover:bg-hover hover:text-content-primary"
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

        <div
          class="flex h-8 w-8 items-center justify-center rounded-full bg-brand-blue text-xs font-bold text-white"
          title={data.user?.email || 'stefan@example.com'}
        >
          {userInitials}
        </div>
      </div>
    </header>

    <!-- Page Content -->
    <main>
      {@render children()}
    </main>
  </div>
</div>
