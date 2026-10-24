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

<section class="card mb-6 grid grid-cols-1 overflow-hidden divide-y divide-border-subtle sm:grid-cols-3 sm:divide-y-0 sm:divide-x" aria-label="Scan Telemetry">
  <div class="p-4 sm:p-5">
    <div class="text-lg font-bold tracking-tight text-content-primary sm:text-xl">{feedsOnline} / {totalFeeds}</div>
    <div class="mt-0.5 text-xs text-content-caption">Feeds checked · All systems healthy</div>
  </div>
  <div class="p-4 sm:p-5">
    <div class="text-lg font-bold tracking-tight text-content-primary sm:text-xl">{scanTime}</div>
    <div class="mt-0.5 text-xs text-content-caption">Daily scan completed</div>
  </div>
  <div class="p-4 sm:p-5">
    <div class="text-lg font-bold tracking-tight text-brand-blue sm:text-xl">{matchesCount} Matching Roles</div>
    <div class="mt-0.5 text-xs text-content-caption">Filtered for UK, EU &amp; Remote</div>
  </div>
</section>
