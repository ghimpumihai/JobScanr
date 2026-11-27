<script lang="ts">
  import { page } from '$app/state';
  import type { ActionData } from './$types';

  let { form }: { form: ActionData } = $props();

  // /auth/callback reports a failed Google sign-in through ?error=
  const error = $derived(form?.error ?? page.url.searchParams.get('error'));
</script>

<svelte:head><title>JobScanr · Sign in</title></svelte:head>

<div class="lg">
  <section class="lg-hero">
    <div style="font-weight: 800; font-size: 24px; letter-spacing: -0.02em">JobScanr</div>
    <div style="display: flex; flex-direction: column; gap: 22px; max-width: 640px">
      <h1 class="lg-title" style="margin: 0; font-size: 64px; font-weight: 800; letter-spacing: -0.04em; line-height: 1">
        Every morning, the roles worth your time. One at a time.
      </h1>
      <p class="lg-lead" style="margin: 0; font-size: 19px; line-height: 1.55; color: #c9cfda; max-width: 52ch">
        At 06:00 UTC JobScanr reads the job boards of 3,600+ companies across Europe directly, keeps the engineering roles that
        fit you, and lines them up. You decide on each one and apply on the employer’s site.
      </p>
    </div>
    <div class="lg-cards" aria-hidden="true" style="display: flex; gap: 18px; align-items: flex-end">
      <div class="lg-card">
        <span class="chip" style="align-self: flex-start">via Lever</span>
        <div>
          <div style="font-size: 44px; font-weight: 800; letter-spacing: -0.04em">€78k</div>
          <div style="margin-top: 10px; font-size: 14px; color: #c9cfda">Dublin · Remote EU</div>
          <div style="font-size: 22px; font-weight: 800; letter-spacing: -0.02em; line-height: 1.1">New Grad Backend Developer</div>
        </div>
      </div>
      <div class="lg-ghost" style="width: 240px; height: 240px; opacity: 0.55"></div>
      <div class="lg-ghost" style="width: 190px; height: 190px; opacity: 0.3"></div>
    </div>
  </section>

  <section class="lg-panel">
    <div style="display: flex; flex-direction: column; gap: 20px; max-width: 380px; width: 100%; margin: 0 auto">
      <h2 style="margin: 0; font-size: 28px; font-weight: 800; letter-spacing: -0.02em">Sign in</h2>
      {#if error}
        <div class="alert" role="alert">{error}</div>
      {/if}
      <form method="POST" action="?/google">
        <button class="google" type="submit">
          <svg width="20" height="20" viewBox="0 0 48 48" aria-hidden="true"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"></path><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"></path><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"></path><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"></path></svg>
          Continue with Google
        </button>
      </form>
      <p style="margin: 0; font-size: 14px; line-height: 1.55; color: #9aa3b2">
        We use your Google account only to sign you in. Your CV and details stay in JobScanr.
      </p>
      <div style="height: 1px; background: #2a2e37"></div>
      <a href="/inbox?demo=true" style="display: inline-flex; align-items: center; gap: 8px; min-height: 44px; font-weight: 700; font-size: 15px; text-decoration: none">
        Explore the demo, no account needed
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"></path></svg>
      </a>
    </div>
  </section>
</div>
