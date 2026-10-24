<script lang="ts">
  import TelemetryStrip from '$lib/components/TelemetryStrip.svelte';
  import Icon from '$lib/components/Icon.svelte';
  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();

  let toastMessage = $state<string | null>(null);

  function showToast(msg: string) {
    toastMessage = msg;
    setTimeout(() => {
      toastMessage = null;
    }, 3500);
  }

  function handleReviewQueue(company: string, role: string) {
    showToast(`Queued ${role} at ${company} for screening answer review.`);
  }

  function handleQueueAll() {
    showToast('Queued all 3 direct matches for review.');
  }
</script>

<svelte:head>
  <title>Daily Matches · JobScanr</title>
</svelte:head>

<!-- Telemetry Summary Strip -->
<TelemetryStrip
  feedsOnline={388}
  totalFeeds={388}
  scanTime="06:00 UTC"
  matchesCount={data.matches.length}
/>

<!-- Main Matches Card -->
<div class="card overflow-hidden">
  <div class="border-b border-border-subtle p-6 sm:p-7">
    <div class="flex items-center justify-between gap-3">
      <h1 class="text-base font-bold leading-snug text-content-primary sm:text-lg">
        Daily Matching Roles (06:00 UTC)
      </h1>
      <button
        type="button"
        class="btn-action shrink-0 !py-1.5 sm:!py-2 !text-xs sm:!text-[13px]"
        onclick={handleQueueAll}
      >
        Queue All Direct (3)
        <Icon name="arrow-right" size={12} />
      </button>
    </div>
    <p class="mt-1.5 text-xs text-content-muted">
      Scanned 388 engineering career boards across Europe for
      <strong class="text-content-primary">stefan@example.com</strong>
    </p>
  </div>

  <div class="px-6 py-3 sm:px-8 sm:py-4">
    <!-- Desktop Table View -->
    <table class="hidden w-full border-collapse sm:table">
      <tbody>
        {#each data.matches as match (match.id)}
          <tr class="border-b border-border-subtle transition-colors last:border-b-0 hover:bg-subtle/30">
            <td class="py-5 align-top sm:py-5.5">
              <div>
                <a
                  href={match.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  class="text-[15px] font-semibold text-brand-blue hover:underline"
                >
                  {match.title}
                </a>
              </div>
              <div class="mb-2 mt-0.5 text-xs font-medium text-content-secondary">
                {match.company_name} · {match.location}
              </div>
              <div class="flex flex-wrap items-center gap-2">
                {#if match.compensation}
                  <span class="tag-salary">{match.compensation}</span>
                {/if}
                <span class="tag-platform">via {match.ats_platform.charAt(0).toUpperCase() + match.ats_platform.slice(1)}</span>
                <span class="tag-score">{match.match_score}% Match</span>
              </div>
            </td>
            <td class="py-5 pl-6 text-right align-middle sm:py-5.5 sm:pl-8">
              {#if match.ats_platform === 'workday'}
                <a
                  href={match.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  class="btn-secondary"
                >
                  Apply Direct
                  <Icon name="external-link" size={12} />
                </a>
              {:else}
                <button
                  type="button"
                  class="btn-action"
                  onclick={() => handleReviewQueue(match.company_name, match.title)}
                >
                  Review &amp; Queue
                  <Icon name="arrow-right" size={12} />
                </button>
              {/if}
            </td>
          </tr>
        {:else}
          <tr>
            <td colspan="2" class="py-12 text-center text-xs text-content-caption">
              No matching positions discovered in the latest scan. Adjust your preferred locations or seniority criteria in Settings.
            </td>
          </tr>
        {/each}
      </tbody>
    </table>

    <!-- Mobile Responsive Card Rows (Title & Button on same line) -->
    <div class="divide-y divide-border-subtle sm:hidden">
      {#each data.matches as match (match.id)}
        <div class="py-4.5 transition-colors hover:bg-subtle/30">
          <!-- Top row: Title on left, Action on right (same line) -->
          <div class="flex items-start justify-between gap-3">
            <a
              href={match.url}
              target="_blank"
              rel="noopener noreferrer"
              class="text-[15px] font-semibold leading-snug text-brand-blue hover:underline"
            >
              {match.title}
            </a>
            <div class="shrink-0">
              {#if match.ats_platform === 'workday'}
                <a
                  href={match.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  class="btn-secondary !py-1 !text-xs whitespace-nowrap"
                >
                  Apply Direct
                  <Icon name="external-link" size={12} />
                </a>
              {:else}
                <button
                  type="button"
                  class="btn-action !py-1 !text-xs whitespace-nowrap"
                  onclick={() => handleReviewQueue(match.company_name, match.title)}
                >
                  Review &amp; Queue
                  <Icon name="arrow-right" size={12} />
                </button>
              {/if}
            </div>
          </div>

          <!-- Second row: Company · Location -->
          <div class="mb-2 mt-1 text-xs font-medium text-content-secondary">
            {match.company_name} · {match.location}
          </div>

          <!-- Third row: Tags -->
          <div class="flex flex-wrap items-center gap-2">
            {#if match.compensation}
              <span class="tag-salary">{match.compensation}</span>
            {/if}
            <span class="tag-platform">via {match.ats_platform.charAt(0).toUpperCase() + match.ats_platform.slice(1)}</span>
            <span class="tag-score">{match.match_score}% Match</span>
          </div>
        </div>
      {:else}
        <div class="py-12 text-center text-xs text-content-caption">
          No matching positions discovered in the latest scan. Adjust your preferred locations or seniority criteria in Settings.
        </div>
      {/each}
    </div>
  </div>
</div>

<!-- Toast Notice -->
{#if toastMessage}
  <div class="fixed bottom-6 right-6 z-50 rounded-md bg-content-primary px-5 py-3 text-xs font-medium text-card shadow-lg transition-all">
    {toastMessage}
  </div>
{/if}
