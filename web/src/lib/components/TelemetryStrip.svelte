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

<section class="card mb-5 grid grid-cols-1 overflow-hidden sm:grid-cols-3" aria-label="Scan Telemetry">
  <div class="border-b border-border-subtle p-3.5 sm:border-b-0 sm:border-r">
    <div class="text-base font-bold text-content-primary">{feedsOnline} / {totalFeeds}</div>
    <div class="mt-0.5 text-xs text-content-caption">Feeds checked · All systems healthy</div>
  </div>
  <div class="border-b border-border-subtle p-3.5 sm:border-b-0 sm:border-r">
    <div class="text-base font-bold text-content-primary">{scanTime}</div>
    <div class="mt-0.5 text-xs text-content-caption">Daily scan completed</div>
  </div>
  <div class="p-3.5">
    <div class="text-base font-bold text-brand-blue">{matchesCount} Matching Roles</div>
    <div class="mt-0.5 text-xs text-content-caption">Filtered for UK, EU &amp; Remote</div>
  </div>
</section>
