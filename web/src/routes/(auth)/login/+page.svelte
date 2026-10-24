<script lang="ts">
  import { enhance } from '$app/forms';
  import Icon from '$lib/components/Icon.svelte';
  import type { ActionData } from './$types';

  let { form }: { form: ActionData } = $props();

  let emailSent = $state(false);
  let userEmail = $state('');
  let loading = $state(false);

  $effect(() => {
    if (form?.success && form?.email) {
      emailSent = true;
      userEmail = form.email;
    }
  });
</script>

<div class="flex min-h-[70vh] items-center justify-center py-12">
  <div class="card w-full max-w-md p-8 shadow-sm">
    <div class="mb-6 text-center">
      <h1 class="text-2xl font-bold tracking-tight text-content-primary">JobScanr</h1>
      <p class="mt-1 text-xs text-content-caption">Sign in to your daily European engineering career radar</p>
    </div>

    {#if form?.error}
      <div class="mb-4 rounded-md border border-signal-amber-border bg-signal-amber-bg p-3 text-xs font-medium text-signal-amber-text">
        {form.error}
      </div>
    {/if}

    {#if !emailSent}
      <form
        method="POST"
        action="?/sendOtp"
        use:enhance={() => {
          loading = true;
          return async ({ update }) => {
            loading = false;
            await update();
          };
        }}
        class="space-y-4"
      >
        <div>
          <label for="email" class="mb-1 block text-xs font-semibold text-content-primary">
            Work or Personal Email
          </label>
          <input
            id="email"
            name="email"
            type="email"
            required
            placeholder="stefan@example.com"
            class="w-full rounded-md border border-border-strong bg-card px-3 py-2 text-xs text-content-primary outline-none transition-colors focus:border-brand-blue"
          />
          <p class="mt-1 text-[11px] text-content-caption">
            We will email you a secure login link and 6-digit confirmation code.
          </p>
        </div>

        <button
          type="submit"
          disabled={loading}
          class="btn-action w-full justify-center py-2 text-xs font-semibold disabled:opacity-60"
        >
          {loading ? 'Sending code...' : 'Continue with Email'}
          <Icon name="arrow-right" size={12} />
        </button>
      </form>
    {:else}
      <form
        method="POST"
        action="?/verifyOtp"
        use:enhance={() => {
          loading = true;
          return async ({ update }) => {
            loading = false;
            await update();
          };
        }}
        class="space-y-4"
      >
        <div class="rounded-md border border-border-main bg-subtle p-3 text-xs text-content-secondary">
          Code sent to <strong>{userEmail}</strong>. Check your inbox or enter code below:
        </div>

        <input type="hidden" name="email" value={userEmail} />

        <div>
          <label for="token" class="mb-1 block text-xs font-semibold text-content-primary">
            6-Digit Verification Code
          </label>
          <input
            id="token"
            name="token"
            type="text"
            required
            maxlength="6"
            pattern="[0-9]{6}"
            placeholder="123456"
            class="w-full rounded-md border border-border-strong bg-card px-3 py-2 font-mono text-center text-sm font-bold tracking-widest text-content-primary outline-none transition-colors focus:border-brand-blue"
          />
        </div>

        <button
          type="submit"
          disabled={loading}
          class="btn-action w-full justify-center py-2 text-xs font-semibold disabled:opacity-60"
        >
          {loading ? 'Verifying...' : 'Sign In to JobScanr'}
          <Icon name="arrow-right" size={12} />
        </button>

        <div class="text-center">
          <button
            type="button"
            onclick={() => (emailSent = false)}
            class="text-[11px] text-content-caption underline hover:text-content-primary"
          >
            Use a different email
          </button>
        </div>
      </form>
    {/if}

    <div class="mt-6 border-t border-border-subtle pt-4 text-center">
      <a
        href="/matches"
        class="inline-flex items-center gap-1.5 text-xs font-semibold text-brand-blue hover:underline"
      >
        <span>Explore Demo Mode (Bypass to Matches)</span>
        <Icon name="arrow-right" size={11} />
      </a>
    </div>
  </div>
</div>
