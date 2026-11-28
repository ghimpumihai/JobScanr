<script lang="ts">
  // One shell for every signed-in page (#141): side menu on desktop, 60px top bar and bottom tab bar on phone.
  import { page } from '$app/state';
  import type { Snippet } from 'svelte';
  import type { LayoutData } from './$types';

  let { children, data }: { children: Snippet; data: LayoutData } = $props();

  let menuOpen = $state(false);
  const label = $derived(data.account.name || data.account.email || 'Demo');
  const initials = $derived(
    (data.account.name || data.account.email || 'D')
      .split(/[\s@.]+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0]?.toUpperCase())
      .join('')
  );
  const onInbox = $derived(page.url.pathname.startsWith('/inbox'));
  // On phone an open role is its own page, without the tab bar.
  const open = $derived(page.url.pathname === '/inbox' && page.url.searchParams.has('role'));

  // Close the account menu on navigation and on Escape.
  $effect(() => {
    void page.url.href;
    menuOpen = false;
  });
  function onkeydown(e: KeyboardEvent) {
    if (e.key === 'Escape' && menuOpen) menuOpen = false;
  }
</script>

<svelte:window {onkeydown} />

{#snippet signOut()}
  <form method="POST" action="/login?/logout">
    <button class="mi" role="menuitem" type="submit">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3"></path><path d="M10 16l-4-4 4-4M6 12h10"></path></svg>
      Sign out
    </button>
  </form>
{/snippet}

<div class="app" class:open>
  <nav class="side" aria-label="Main">
    <a class="brand" href="/inbox">JobScanr</a>
    <div class="nav-links">
      <a class="nav-link" class:is-current={onInbox} href="/inbox" aria-current={onInbox ? 'page' : undefined}>
        Inbox {#if data.inboxCount !== null}<span class="count">{data.inboxCount}</span>{/if}
      </a>
      <a class="nav-link" class:is-current={!onInbox} href="/settings" aria-current={!onInbox ? 'page' : undefined}>Settings</a>
    </div>
    <button class="acct-mini" type="button" aria-label="Account: {label}" aria-haspopup="menu" aria-expanded={menuOpen} onclick={() => (menuOpen = !menuOpen)}>{initials}</button>
    <div class="nav-foot">
      <div class="scan"><b>Scanned {data.scan.last}, 06:00 UTC</b><span>Next scan {data.scan.next}, 06:00 UTC</span></div>
      {#if menuOpen}
        <div class="menu" role="menu" aria-label="Account">{@render signOut()}</div>
      {/if}
      <button class="acct" type="button" aria-haspopup="menu" aria-expanded={menuOpen} onclick={() => (menuOpen = !menuOpen)}>
        <span class="avatar" aria-hidden="true">{initials}</span>
        <span class="acct-text">
          <span class="one" style="font-size: 14px; font-weight: 800; color: #ffffff">{label}</span>
          {#if data.account.name}<span class="one" style="font-size: 12px; color: #9aa3b2">{data.account.email}</span>{/if}
        </span>
      </button>
    </div>
    {#if menuOpen}
      <button class="scrim" type="button" aria-label="Close account menu" onclick={() => (menuOpen = false)}></button>
      <div class="sheet" role="menu" aria-label="Account">
        <div style="padding: 10px 12px 12px; margin-bottom: 6px; border-bottom: 1px solid #1d2026; display: flex; align-items: center; gap: 12px">
          <span class="avatar" aria-hidden="true" style="width: 40px; height: 40px">{initials}</span>
          <span style="min-width: 0">
            <span class="one" style="display: block; font-size: 15px; font-weight: 800">{label}</span>
            {#if data.account.name}<span class="one" style="display: block; font-size: 13px; color: #9aa3b2">{data.account.email}</span>{/if}
          </span>
        </div>
        {@render signOut()}
      </div>
    {/if}
  </nav>

  {@render children()}

  <nav class="tabbar" aria-label="Main">
    <a class="tb" href="/inbox" aria-current={onInbox ? 'page' : undefined}>
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 13l2.5-7h11L20 13v6H4z"></path><path d="M4 13h5l1 2h4l1-2h5"></path></svg>
      Inbox
    </a>
    <a class="tb" href="/settings" aria-current={!onInbox ? 'page' : undefined}>
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="8" r="4"></circle><path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6"></path></svg>
      Settings
    </a>
  </nav>
</div>
