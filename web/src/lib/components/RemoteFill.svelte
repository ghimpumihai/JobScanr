<script lang="ts">
  // "Fill it for me" (#129, trial): a remote browser fills the employer's form; the user reviews it in the live view
  // and clicks Submit there. JobScanr never submits; Applied is recorded only from the employer's confirmation page.
  import { deserialize } from '$app/forms';
  import { invalidateAll } from '$app/navigation';
  import { startUnlessClosed } from '$lib/remoteFillStart';

  let { applicationId, provider }: { applicationId: number; provider: string } = $props();

  type State =
    | { step: 'idle' }
    | { step: 'consent' }
    | { step: 'starting' }
    | { step: 'open'; sessionId: number; liveViewUrl: string; leftForUser: string[]; captcha: boolean }
    | { step: 'done'; text: string }
    | { step: 'error'; text: string };

  let ui = $state<State>({ step: 'idle' });
  // Each step replaces the control that was pressed, so focus moves to the new step instead of falling to the page.
  // Not on first render: the drawer itself decides where focus starts.
  let moved = $state(false);
  const focusHere = (node: HTMLElement) => {
    if (moved) node.focus();
  };
  function go(next: State) {
    moved = true;
    ui = next;
  }

  async function call(action: string, id: number): Promise<any> {
    const body = new FormData();
    body.set('id', String(id));
    // Absolute: the panel can outlive a navigation away from /applications.
    const res = await fetch(`/applications?/${action}`, { method: 'POST', body, headers: { 'x-sveltekit-action': 'true' } });
    const result = deserialize(await res.text());
    if (result.type === 'success') return (result.data as { remote: unknown }).remote;
    if (result.type === 'failure') throw new Error(String(result.data?.error ?? 'Something went wrong.'));
    throw new Error('The request failed. Use the Apply link instead.');
  }

  // Plain, not $state: only read after an await, to see whether the drawer was closed meanwhile.
  let mounted = true;

  async function start() {
    go({ step: 'starting' });
    try {
      const r = await startUnlessClosed(
        () => call('remoteStart', applicationId),
        (id) => call('remoteEnd', id),
        () => mounted
      );
      if (!r) return; // the drawer closed meanwhile; that session is already ended
      ui ={ step: 'open', sessionId: r.sessionId, liveViewUrl: r.liveViewUrl, leftForUser: r.leftForUser, captcha: false };
    } catch (e) {
      ui = { step: 'error', text: (e as Error).message };
    }
  }

  async function finish(result: { state: string }) {
    if (result.state === 'submitted') {
      ui = { step: 'done', text: 'The employer confirmed your application. It is now in Applied.' };
      await invalidateAll();
    } else if (result.state === 'unrecorded') {
      ui = { step: 'done', text: 'The employer confirmed your application, but JobScanr could not record it. Press I applied below.' };
    } else if (result.state !== 'open') {
      ui = { step: 'done', text: 'The session ended. Nothing was recorded; mark it yourself if you did apply.' };
    }
  }

  async function end() {
    if (ui.step !== 'open') return;
    const id = ui.sessionId;
    try {
      await finish(await call('remoteEnd', id));
    } catch (e) {
      ui = { step: 'error', text: (e as Error).message };
    }
  }

  // Poll every 3 s while the live view is open; the server records Applied on the confirmation page.
  $effect(() => {
    if (ui.step !== 'open') return;
    const id = ui.sessionId;
    let busy = false;
    const timer = setInterval(async () => {
      if (busy) return;
      busy = true;
      try {
        const r = await call('remotePoll', id);
        if (ui.step === 'open' && r.state === 'open') ui.captcha = Boolean(r.captcha);
        else await finish(r);
      } catch {
        // A failed poll is retried; the server closes the session after 13 minutes regardless.
      } finally {
        busy = false;
      }
    }, 3000);
    return () => clearInterval(timer);
  });

  // The live view tells its parent when the remote browser goes away.
  $effect(() => {
    if (ui.step !== 'open') return;
    const origin = new URL(ui.liveViewUrl).origin;
    const onMessage = (e: MessageEvent) => {
      if (e.origin === origin && e.data === 'browserbase-disconnected') void end();
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  });

  // Closing the drawer mid-session ends it; keepalive lets the request finish as the component goes away.
  $effect(() => () => {
    mounted = false;
    if (ui.step !== 'open') return;
    const body = new FormData();
    body.set('id', String(ui.sessionId));
    void fetch('/applications?/remoteEnd', { method: 'POST', body, headers: { 'x-sveltekit-action': 'true' }, keepalive: true }).catch(() => {});
  });
</script>

<section class="space-y-2 rounded-md border border-border-main p-4" aria-labelledby="remoteFillTitle">
  <h3 id="remoteFillTitle" class="text-xs font-semibold text-content-primary">Fill it for me <span class="font-normal text-content-caption">(trial)</span></h3>

  {#if ui.step === 'idle'}
    <p class="text-xs text-content-muted">JobScanr fills the employer's form for you. You check it and click Submit yourself.</p>
    <button type="button" class="btn-action !text-xs" onclick={() => go({ step: 'consent' })} {@attach focusHere}>Fill it for me</button>
  {:else if ui.step === 'consent'}
    <div class="space-y-2 text-xs text-content-muted">
      <p>
        Your name, contact details, links and CV are loaded into a browser run by {provider}, a third-party service, for
        this one application. The session ends when you close it or after 13 minutes.
      </p>
      <p>JobScanr never clicks Submit. Check every answer before you submit it.</p>
    </div>
    <div class="flex flex-wrap gap-2">
      <button type="button" class="btn-action !text-xs" onclick={start} {@attach focusHere}>I agree, start</button>
      <button type="button" class="btn-secondary !text-xs" onclick={() => go({ step: 'idle' })}>Cancel</button>
    </div>
  {:else if ui.step === 'starting'}
    <p class="text-xs text-content-muted" role="status" tabindex="-1" {@attach focusHere}>
      Opening and filling the form. This can take up to a minute.
    </p>
  {:else if ui.step === 'open'}
    {#if ui.leftForUser.length}
      <div class="text-xs">
        <p class="font-semibold text-content-primary">Left for you to answer:</p>
        <ul class="ml-4 list-disc text-content-muted">
          {#each ui.leftForUser as label, i (i)}
            <li>{label}</li>
          {/each}
        </ul>
      </div>
    {/if}
    {#if ui.captcha}
      <p class="text-xs text-content-muted" role="status">The employer's site is asking for a captcha. Please solve it in the form.</p>
    {/if}
    <iframe
      {@attach focusHere}
      src={ui.liveViewUrl}
      title="Application form for you to review and submit"
      class="h-[70vh] w-full rounded-md border border-border-main"
      sandbox="allow-same-origin allow-scripts"
      allow="clipboard-read; clipboard-write"
    ></iframe>
    <p class="text-[11px] text-content-caption" role="status">
      When the employer shows its confirmation, this application moves to Applied by itself.
    </p>
    <button type="button" class="btn-secondary !text-xs" onclick={end}>Close the form</button>
  {:else if ui.step === 'done'}
    <p class="text-xs text-content-muted" role="status" tabindex="-1" {@attach focusHere}>{ui.text}</p>
  {:else}
    <p class="text-xs text-red-600" role="alert">{ui.text} You can still use the Apply link below.</p>
    <button type="button" class="btn-secondary !text-xs" onclick={() => go({ step: 'idle' })} {@attach focusHere}>Try again</button>
  {/if}
</section>
