<script lang="ts">
  interface Props {
    feedsOnline?: number;
    totalFeeds?: number;
    scanTime?: string;
    matchesCount?: number;
  }

  let {
    feedsOnline = 388,
    totalFeeds = 388,
    scanTime = '06:00 UTC',
    matchesCount = 4
  }: Props = $props();
</script>

<section class="card mb-8 grid grid-cols-1 overflow-hidden divide-y divide-border-subtle sm:grid-cols-3 sm:divide-y-0 sm:divide-x" aria-label="Scan Telemetry">
  <div class="p-5 sm:p-6">
    <div class="text-xl font-bold tracking-tight text-content-primary sm:text-2xl">{feedsOnline} / {totalFeeds}</div>
    <div class="mt-1 text-xs text-content-caption">Feeds checked · All systems healthy</div>
  </div>
  <div class="p-5 sm:p-6">
    <div class="text-xl font-bold tracking-tight text-content-primary sm:text-2xl">{scanTime}</div>
    <div class="mt-1 text-xs text-content-caption">Daily scan completed</div>
  </div>
  <div class="p-5 sm:p-6">
    <div class="text-xl font-bold tracking-tight text-brand-blue sm:text-2xl">{matchesCount} Matching Roles</div>
    <div class="mt-1 text-xs text-content-caption">Filtered for UK, EU &amp; Remote</div>
  </div>
</section>
