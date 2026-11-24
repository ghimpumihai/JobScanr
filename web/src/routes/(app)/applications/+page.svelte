<script lang="ts">
  import { enhance } from '$app/forms';
  import type { SubmitFunction } from '@sveltejs/kit';
  import ApplyDrawer from '$lib/components/ApplyDrawer.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import type { ApplicationRecord, ATSPlatform } from '$lib/types';
  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();

  const TABS = [
    { key: 'to_apply', label: 'To Apply', empty: 'Nothing to apply to. New matches appear here after the daily scan.' },
    { key: 'applied', label: 'Applied', empty: 'Roles you mark as applied appear here.' },
    { key: 'not_interested', label: 'Not Interested', empty: 'Roles you mark as not interested appear here.' },
    { key: 'closed', label: 'Closed', empty: 'Roles whose posting is gone for 30 days appear here.' }
  ] as const;
  const PLATFORMS: ATSPlatform[] = ['greenhouse', 'lever', 'workday', 'ashby', 'smartrecruiters', 'teamtailor', 'google'];

  type Undo = { id: number; from: string; to: string };
  let selectedId = $state<number | null>(null);
  let pending = $state(false);
  let notice = $state<{ text: string; error: boolean; undo: Undo | null } | null>(null);

  // Looked up from the loaded rows, so the drawer closes when its row leaves this tab.
  const selected = $derived(data.applications.find((a) => a.id === selectedId) ?? null);
  const tab = $derived(TABS.find((t) => t.key === data.tab) ?? TABS[0]);
  const pageCount = $derived(Math.max(1, Math.ceil(data.counts[data.tab] / data.pageSize)));

  const day = (iso: string | null) =>
    iso ? new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }) : '—';
  const platformName = (p: string) => p.charAt(0).toUpperCase() + p.slice(1);

  /** A link to this list with some parameters changed; empty values are left out. */
  function listHref(changes: Record<string, string | number>) {
    const params = { tab: data.tab, ...data.filters, page: data.page, ...changes };
    const query = new URLSearchParams(
      Object.entries(params)
        .filter(([key, value]) => value !== '' && !(key === 'page' && value === 1) && !(key === 'tab' && value === 'to_apply'))
        .map(([key, value]) => [key, String(value)])
    ).toString();
    return query ? `?${query}` : '?';
  }

  const submit: SubmitFunction = () => {
    pending = true;
    return async ({ result, update }) => {
      pending = false;
      if (result.type === 'success') {
        notice = { text: String(result.data?.message ?? 'Saved.'), error: false, undo: (result.data?.undo as Undo) ?? null };
        selectedId = null;
      } else if (result.type === 'failure') {
        notice = { text: String(result.data?.error ?? 'Could not change this application.'), error: true, undo: null };
      } else if (result.type === 'error') {
        // Not update(): if the server is unreachable it would replace the page with an error page.
        notice = { text: 'The request failed, so the outcome is unknown. Reload the page to check.', error: true, undo: null };
        return;
      }
      // Reloads the list, including after "already changed" or an unknown outcome, so the row shows its real status.
      await update({ reset: false });
    };
  };
</script>

<svelte:head>
  <title>Applications · JobScanr</title>
</svelte:head>

{#snippet change(app: ApplicationRecord, to: string, label: string, primary = false)}
  <form method="POST" action="?/setStatus" use:enhance={submit}>
    <input type="hidden" name="id" value={app.id} />
    <input type="hidden" name="from" value={app.status} />
    <input type="hidden" name="to" value={to} />
    <button
      type="submit"
      class="{primary ? 'btn-action' : 'btn-secondary'} !py-1 !text-xs whitespace-nowrap disabled:opacity-60"
      disabled={pending}
      aria-label="{label}: {app.title} at {app.company_name}"
    >
      {label}
    </button>
  </form>
{/snippet}

{#snippet rowActions(app: ApplicationRecord)}
  {#if app.status === 'manual_apply' || app.status === 'stale_closed'}
    <button
      type="button"
      class="btn-action !py-1 !text-xs whitespace-nowrap"
      onclick={() => (selectedId = app.id)}
      aria-label="Apply: {app.title} at {app.company_name}"
    >
      Apply
    </button>
    {@render change(app, 'submitted', 'Applied')}
    {@render change(app, 'dismissed', 'Not interested')}
  {:else if app.status === 'dismissed' || (app.status === 'submitted' && app.applied_at)}
    {@render change(app, 'manual_apply', 'Move to To Apply')}
  {/if}
{/snippet}

{#snippet drawerActions(app: ApplicationRecord)}
  {@render change(app, 'dismissed', 'Not interested')}
  {@render change(app, 'submitted', 'I applied', true)}
{/snippet}

<div class="card overflow-hidden">
  <div class="border-b border-border-subtle p-6 sm:p-7">
    <h1 class="text-lg font-bold leading-snug text-content-primary">Applications</h1>
    <p class="mt-1 text-xs text-content-muted">
      Apply on each employer's site, then mark the role here. JobScanr does not submit applications for you.
    </p>
    {#if data.demo}
      <p class="mt-2 text-xs font-semibold text-content-secondary">Demo: these roles are examples and changes are not stored.</p>
    {/if}
  </div>

  {#if data.loadError}
    <div class="m-6 border-l-4 border-red-500 p-4 text-xs text-content-primary" role="alert">
      Could not load your applications. Please reload the page.
    </div>
  {:else}
    <nav aria-label="Application status" class="flex flex-wrap gap-1 border-b border-border-subtle px-6 pt-3 sm:px-8">
      {#each TABS as t (t.key)}
        <a
          href={listHref({ tab: t.key, page: 1 })}
          aria-current={t.key === data.tab ? 'page' : undefined}
          class="-mb-px border-b-2 px-3 py-2 text-xs font-semibold {t.key === data.tab
            ? 'border-brand-blue text-content-primary'
            : 'border-transparent text-content-muted hover:text-content-primary'}"
        >
          {t.label} <span class="font-mono text-content-caption">{data.counts[t.key]}</span>
        </a>
      {/each}
    </nav>

    <form method="GET" class="flex flex-wrap items-end gap-3 border-b border-border-subtle px-6 py-4 text-xs sm:px-8">
      {#if data.tab !== 'to_apply'}<input type="hidden" name="tab" value={data.tab} />{/if}
      <label class="flex flex-col gap-1">
        <span class="font-semibold text-content-primary">Platform</span>
        <select name="platform" class="rounded-md border border-border-strong bg-card px-2 py-1.5">
          <option value="">All</option>
          {#each PLATFORMS as p (p)}
            <option value={p} selected={data.filters.platform === p}>{platformName(p)}</option>
          {/each}
        </select>
      </label>
      <label class="flex flex-col gap-1">
        <span class="font-semibold text-content-primary">Company</span>
        <input
          name="company"
          value={data.filters.company}
          maxlength="100"
          class="w-40 rounded-md border border-border-strong bg-card px-2 py-1.5"
        />
      </label>
      <label class="flex flex-col gap-1">
        <span class="font-semibold text-content-primary">{data.tab === 'applied' ? 'Applied from' : 'Added from'}</span>
        <input type="date" name="from" value={data.filters.from} class="rounded-md border border-border-strong bg-card px-2 py-1" />
      </label>
      <label class="flex flex-col gap-1">
        <span class="font-semibold text-content-primary">to</span>
        <input type="date" name="to" value={data.filters.to} class="rounded-md border border-border-strong bg-card px-2 py-1" />
      </label>
      <button type="submit" class="btn-secondary !py-1.5 !text-xs">Filter</button>
      <a href={listHref({ platform: '', company: '', from: '', to: '', page: 1 })} class="py-1.5 text-content-muted underline">
        Clear
      </a>
    </form>

    <div class="overflow-x-auto px-6 py-2 sm:px-8">
      <table class="w-full border-collapse text-left">
        <thead class="sr-only sm:not-sr-only">
          <tr class="border-b border-border-main text-xs font-semibold uppercase tracking-wider text-content-caption">
            <th class="py-3">Role &amp; Company</th>
            <th class="hidden py-3 sm:table-cell">Platform</th>
            <th class="hidden py-3 sm:table-cell">Added</th>
            <th class="hidden py-3 sm:table-cell">Applied</th>
            <th class="py-3 text-right">Action</th>
          </tr>
        </thead>
        <tbody>
          {#each data.applications as app (app.id)}
            <tr class="border-b border-border-subtle align-top last:border-b-0">
              <td class="py-4 pr-3">
                <div class="text-[15px] font-semibold text-content-primary">{app.title}</div>
                <div class="mt-0.5 text-xs text-content-secondary">
                  {app.company_name}{app.location ? ` · ${app.location}` : ''}
                </div>
                <div class="mt-1 text-xs text-content-caption sm:hidden">
                  {platformName(app.ats_platform)} · added {day(app.added_at)}{app.applied_at ? ` · applied ${day(app.applied_at)}` : ''}
                </div>
                {#if app.status === 'stale_closed'}
                  <div class="mt-1 text-xs text-content-caption">Posting last seen {day(app.last_seen_at)}</div>
                {/if}
              </td>
              <td class="hidden py-4 sm:table-cell"><span class="tag-platform">{platformName(app.ats_platform)}</span></td>
              <td class="hidden py-4 font-mono text-xs text-content-caption sm:table-cell">{day(app.added_at)}</td>
              <td class="hidden py-4 font-mono text-xs text-content-caption sm:table-cell">{day(app.applied_at)}</td>
              <td class="py-4 pl-3">
                <div class="flex flex-wrap justify-end gap-2">{@render rowActions(app)}</div>
              </td>
            </tr>
          {:else}
            <tr>
              <td colspan="5" class="py-12 text-center text-xs text-content-caption">{tab.empty}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    {#if pageCount > 1}
      <nav aria-label="Pages" class="flex items-center justify-between border-t border-border-subtle px-6 py-3 text-xs sm:px-8">
        {#if data.page > 1}
          <a href={listHref({ page: data.page - 1 })} class="btn-secondary !py-1 !text-xs">Previous</a>
        {:else}
          <span></span>
        {/if}
        <span class="text-content-caption">Page {data.page} of {pageCount}</span>
        {#if data.page < pageCount}
          <a href={listHref({ page: data.page + 1 })} class="btn-secondary !py-1 !text-xs">Next</a>
        {:else}
          <span></span>
        {/if}
      </nav>
    {/if}
  {/if}
</div>

<ApplyDrawer
  application={selected}
  profile={data.profile}
  onclose={() => (selectedId = null)}
  actions={drawerActions}
  remoteApply={data.remoteApply}
/>

<!-- The region stays in the page so screen readers announce each new message. -->
<div aria-live="polite" class="fixed bottom-6 right-6 z-40 max-w-[calc(100vw-3rem)]">
  {#if notice}
    <div class="flex items-center gap-3 rounded-md bg-content-primary px-5 py-3 text-xs font-medium text-card shadow-lg">
      <span>{#if notice.error}<strong>Error:</strong>{' '}{/if}{notice.text}</span>
      {#if notice.undo}
        <form method="POST" action="?/setStatus" use:enhance={submit}>
          <input type="hidden" name="id" value={notice.undo.id} />
          <input type="hidden" name="from" value={notice.undo.from} />
          <input type="hidden" name="to" value={notice.undo.to} />
          <button type="submit" class="font-semibold underline" disabled={pending}>Undo</button>
        </form>
      {/if}
      <button type="button" onclick={() => (notice = null)} aria-label="Dismiss message">
        <Icon name="close" size={12} />
      </button>
    </div>
  {/if}
</div>
