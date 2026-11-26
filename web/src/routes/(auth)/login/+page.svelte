<script lang="ts">
  import { page } from '$app/state';
  import Icon from '$lib/components/Icon.svelte';
  import type { ActionData } from './$types';

  let { form }: { form: ActionData } = $props();

  // /auth/callback reports a failed Google sign-in through ?error=
  const error = $derived(form?.error ?? page.url.searchParams.get('error'));
</script>

<div class="flex min-h-[70vh] items-center justify-center py-12">
  <div class="card w-full max-w-md p-8 shadow-sm">
    <div class="mb-6 text-center">
      <h1 class="text-2xl font-bold tracking-tight text-content-primary">JobScanr</h1>
      <p class="mt-1 text-xs text-content-caption">Sign in to your daily European engineering career radar</p>
    </div>

    {#if error}
      <div class="mb-4 rounded-md border border-signal-amber-border bg-signal-amber-bg p-3 text-xs font-medium text-signal-amber-text">
        {error}
      </div>
    {/if}

    <form method="POST" action="?/google">
      <button type="submit" class="btn-action w-full justify-center py-2 text-xs font-semibold">
        Continue with Google
        <Icon name="arrow-right" size={12} />
      </button>
    </form>

    <div class="mt-6 border-t border-border-subtle pt-4 text-center">
      <a
        href="/matches?demo=true"
        class="inline-flex items-center gap-1.5 text-xs font-semibold text-brand-blue hover:underline"
      >
        <span>Explore Demo Mode (Bypass to Matches)</span>
        <Icon name="arrow-right" size={11} />
      </a>
    </div>
  </div>
</div>
