<script lang="ts">
  import Icon from '$lib/components/Icon.svelte';
  import ReviewDrawer from '$lib/components/ReviewDrawer.svelte';
  import type { PageData } from './$types';
  import type { ApplicationRecord } from '$lib/types';

  let { data }: { data: PageData } = $props();

  let selectedApp = $state<ApplicationRecord | null>(null);
  let toastMessage = $state<string | null>(null);

  function showToast(msg: string) {
    toastMessage = msg;
    setTimeout(() => {
      toastMessage = null;
    }, 3500);
  }

  function handleDrawerSubmit(app: ApplicationRecord, answer: string) {
    selectedApp = null;
    showToast(`Application for ${app.title} at ${app.company_name} approved and queued for dispatch.`);
  }
</script>

<svelte:head>
  <title>Application Audit Tracker · JobScanr</title>
</svelte:head>

<div class="card overflow-hidden">
  <div class="border-b border-border-subtle p-6 sm:p-7">
    <h1 class="text-lg font-bold leading-snug text-content-primary">
      Application Audit Tracker
    </h1>
    <p class="mt-1 text-xs text-content-muted">
      Real-time status of submissions dispatched by background worker queue.
    </p>
  </div>

  <!-- Desktop Table View (Hidden on mobile, visible on sm:) -->
  <div class="hidden overflow-x-auto px-6 py-3 sm:block sm:px-8 sm:py-4">
    <table class="w-full border-collapse text-left">
      <thead>
        <tr class="border-b border-border-main text-xs font-semibold uppercase tracking-wider text-content-caption">
          <th class="py-3.5">Role &amp; Company</th>
          <th class="py-3.5">Platform</th>
          <th class="py-3.5">Status</th>
          <th class="py-3.5">Submitted / Scheduled</th>
          <th class="py-3.5 text-right">Action</th>
        </tr>
      </thead>
      <tbody>
        {#each data.applications as app (app.id)}
          <tr class="border-b border-border-subtle transition-colors last:border-b-0 hover:bg-subtle/30">
            <td class="py-5 sm:py-5.5">
              <div class="text-[15px] font-semibold text-content-primary">{app.title}</div>
              <div class="mb-1 mt-0.5 text-xs font-medium text-content-secondary">{app.company_name} · {app.location}</div>
            </td>
            <td class="py-5 sm:py-5.5">
              <span class="tag-platform">via {app.ats_platform.charAt(0).toUpperCase() + app.ats_platform.slice(1)}</span>
            </td>
            <td class="py-5 sm:py-5.5">
              {#if app.status === 'submitted'}
                <span class="status-badge bg-signal-emerald-bg text-signal-emerald-text">
                  Submitted
                </span>
              {:else if app.status === 'needs_review'}
                <span class="status-badge border border-signal-amber-border bg-signal-amber-bg text-signal-amber-text">
                  Needs Review
                </span>
              {:else if app.status === 'queued'}
                <span class="status-badge bg-signal-slate-bg text-signal-slate-text">
                  Queued
                </span>
              {:else}
                <span class="status-badge bg-signal-slate-bg text-signal-slate-text">
                  {app.status}
                </span>
              {/if}
            </td>
            <td class="py-5 font-mono text-xs text-content-caption sm:py-5.5">
              {#if app.status === 'needs_review'}
                <span class="font-sans font-semibold text-signal-amber-text">Action Required</span>
              {:else}
                {app.submitted_at || app.scheduled_at || '—'}
              {/if}
            </td>
            <td class="py-5 pl-4 text-right sm:py-5.5">
              {#if app.status === 'needs_review'}
                <button
                  type="button"
                  class="btn-action"
                  onclick={() => (selectedApp = app)}
                >
                  Review Answers
                  <Icon name="arrow-right" size={12} />
                </button>
              {:else if app.status === 'submitted'}
                <button
                  type="button"
                  class="btn-secondary"
                  onclick={() => showToast(`Submission confirmed by API (Token: ${app.attempt_token || 'gh_app_7a89f0'})`)}
                >
                  View Receipt
                </button>
              {:else}
                <button
                  type="button"
                  class="btn-secondary"
                  onclick={() => showToast(`Queued in worker pool. Rate limit: 30 workers.`)}
                >
                  Inspect
                </button>
              {/if}
            </td>
          </tr>
        {:else}
          <tr>
            <td colspan="5" class="py-12 text-center text-xs text-content-caption">
              No application submissions recorded yet. Roles approved from the daily feed will appear here for audit tracking.
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>

  <!-- Mobile Responsive Card Rows (Title & Button on same line) -->
  <div class="divide-y divide-border-subtle px-6 py-1 sm:hidden">
    {#each data.applications as app (app.id)}
      <div class="py-4.5 transition-colors hover:bg-subtle/30">
        <!-- Top line: Title on left, Action on right (same line) -->
        <div class="flex items-start justify-between gap-3">
          <div class="text-[15px] font-semibold leading-snug text-content-primary">
            {app.title}
          </div>
          <div class="shrink-0">
            {#if app.status === 'needs_review'}
              <button
                type="button"
                class="btn-action !py-1 !text-xs whitespace-nowrap"
                onclick={() => (selectedApp = app)}
              >
                Review Answers
                <Icon name="arrow-right" size={12} />
              </button>
            {:else if app.status === 'submitted'}
              <button
                type="button"
                class="btn-secondary !py-1 !text-xs whitespace-nowrap"
                onclick={() => showToast(`Submission confirmed by API (Token: ${app.attempt_token || 'gh_app_7a89f0'})`)}
              >
                View Receipt
              </button>
            {:else}
              <button
                type="button"
                class="btn-secondary !py-1 !text-xs whitespace-nowrap"
                onclick={() => showToast(`Queued in worker pool. Rate limit: 30 workers.`)}
              >
                Inspect
              </button>
            {/if}
          </div>
        </div>

        <!-- Second line: Company · Location -->
        <div class="mb-2 mt-1 text-xs font-medium text-content-secondary">
          {app.company_name} · {app.location}
        </div>

        <!-- Third line: Badges & Timestamp -->
        <div class="flex flex-wrap items-center gap-2">
          <span class="tag-platform">via {app.ats_platform.charAt(0).toUpperCase() + app.ats_platform.slice(1)}</span>
          {#if app.status === 'submitted'}
            <span class="status-badge bg-signal-emerald-bg text-signal-emerald-text">
              Submitted
            </span>
          {:else if app.status === 'needs_review'}
            <span class="status-badge border border-signal-amber-border bg-signal-amber-bg text-signal-amber-text">
              Needs Review
            </span>
          {:else}
            <span class="status-badge bg-signal-slate-bg text-signal-slate-text">
              {app.status === 'queued' ? 'Queued' : app.status}
            </span>
          {/if}
          <span class="font-mono text-xs text-content-caption">
            {app.status === 'needs_review' ? 'Action Required' : (app.submitted_at || app.scheduled_at || '—')}
          </span>
        </div>
      </div>
    {:else}
      <div class="py-12 text-center text-xs text-content-caption">
        No application submissions recorded yet. Roles approved from the daily feed will appear here for audit tracking.
      </div>
    {/each}
  </div>
</div>

<!-- Slide-over Review Drawer -->
<ReviewDrawer
  application={selectedApp}
  onclose={() => (selectedApp = null)}
  onsubmit={handleDrawerSubmit}
/>

<!-- Toast Notice -->
{#if toastMessage}
  <div class="fixed bottom-6 right-6 z-50 rounded-md bg-content-primary px-5 py-3 text-xs font-medium text-card shadow-lg transition-all">
    {toastMessage}
  </div>
{/if}
