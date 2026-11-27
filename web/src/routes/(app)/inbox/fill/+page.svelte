<script lang="ts">
  // "Fill it for me" (#129, #141): a remote browser fills the employer's form; the user reviews it in the live view
  // and clicks Submit there. JobScanr never submits; Applied is recorded only from the employer's confirmation page.
  import { deserialize } from '$app/forms';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { startUnlessClosed } from '$lib/remoteFillStart';
  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();
  const role = $derived(data.role);
  const company = $derived(`${role.company_name}’${role.company_name.endsWith('s') ? '' : 's'}`);
  const PLATFORM: Record<string, string> = { greenhouse: 'Greenhouse', lever: 'Lever', ashby: 'Ashby' };

  type Draft = { label: string; text: string; note: string; busy: boolean; redrafted: boolean; error: string };
  type Open = { sessionId: number; liveViewUrl: string; leftForUser: string[]; filled: string[]; drafts: Draft[]; captcha: boolean };
  type State =
    | { step: 'starting' }
    | ({ step: 'open' } & Open)
    | { step: 'done'; title: string; text: string }
    | { step: 'error'; title?: string; text: string };

  let ui = $state<State>({ step: 'starting' });
  let progress = $state(0); // the start is one request: the steps advance on a timer and the last waits for it
  const STEPS = $derived([`Opening ${company} form`, 'Typing in your details', 'Attaching your CV', 'Adding saved and drafted answers']);

  async function call(action: string, fields: Record<string, string>): Promise<any> {
    const body = new FormData();
    for (const [k, v] of Object.entries(fields)) body.set(k, v);
    const res = await fetch(`/inbox?/${action}`, { method: 'POST', body, headers: { 'x-sveltekit-action': 'true' } });
    const result = deserialize(await res.text());
    if (result.type === 'success') return (result.data as { remote: unknown }).remote;
    if (result.type === 'failure') throw new Error(String(result.data?.error ?? 'Something went wrong.'));
    throw new Error(`The request failed. Apply on ${company} site instead.`);
  }

  // Plain, not $state: only read after an await, to see whether the page was left meanwhile.
  let mounted = true;

  async function start() {
    ui = { step: 'starting' };
    progress = 0;
    const timer = setInterval(() => (progress = Math.min(progress + 1, STEPS.length - 1)), 6000);
    try {
      const r = await startUnlessClosed(
        () => call('remoteStart', { id: String(role.id) }),
        (id) => call('remoteEnd', { id: String(id) }),
        () => mounted
      );
      if (!r) return; // the page was left meanwhile; that session is already ended
      ui = {
        step: 'open',
        sessionId: r.sessionId,
        liveViewUrl: r.liveViewUrl,
        leftForUser: r.leftForUser ?? [],
        filled: r.filled ?? [],
        drafts: (r.drafts ?? []).map((d: { label: string; text: string }) => ({ ...d, note: '', busy: false, redrafted: false, error: '' })),
        captcha: false
      };
    } catch (e) {
      ui = { step: 'error', text: (e as Error).message };
    } finally {
      clearInterval(timer);
    }
  }

  async function finish(result: { state: string }) {
    if (result.state === 'submitted') {
      ui = { step: 'done', title: `${role.company_name} confirmed your application.`, text: 'It’s in Applied now. Nothing else to do.' };
    } else if (result.state === 'unrecorded') {
      ui = { step: 'done', title: `${role.company_name} confirmed your application.`, text: 'JobScanr could not record it. Go back to the role and press I applied.' };
    } else if (result.state !== 'open') {
      ui = { step: 'error', title: 'The session ended.', text: 'Nothing was recorded; mark the role yourself if you did apply.' };
    }
  }

  // Leaving ends the remote browser now, not at its 13-minute limit (the unmount effect below sends remoteEnd).
  const back = () => goto(`/inbox?role=${role.id}`);

  async function redraft(d: Draft) {
    if (ui.step !== 'open' || d.busy) return;
    d.busy = true;
    d.error = '';
    try {
      const r = await call('remoteRedraft', { id: String(ui.sessionId), label: d.label, note: d.note });
      d.text = r.draft;
      d.redrafted = true;
      if (ui.step === 'open' && Array.isArray(r.leftForUser)) ui.leftForUser = r.leftForUser;
    } catch (e) {
      d.error = (e as Error).message;
    } finally {
      d.busy = false;
    }
  }

  onMount(() => {
    void start();
    return () => {
      mounted = false;
    };
  });

  // Poll every 3 s while the live view is open; the server records Applied on the confirmation page.
  $effect(() => {
    if (ui.step !== 'open') return;
    const id = ui.sessionId;
    let busy = false;
    const timer = setInterval(async () => {
      if (busy) return;
      busy = true;
      try {
        const r = await call('remotePoll', { id: String(id) });
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
      if (e.origin === origin && e.data === 'browserbase-disconnected') {
        const id = (ui as Open).sessionId;
        void call('remoteEnd', { id: String(id) }).then(finish, () => {});
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  });

  // Leaving the page mid-session ends it; keepalive lets the request finish as the page goes away.
  $effect(() => () => {
    if (ui.step !== 'open') return;
    const body = new FormData();
    body.set('id', String(ui.sessionId));
    void fetch('/inbox?/remoteEnd', { method: 'POST', body, headers: { 'x-sveltekit-action': 'true' }, keepalive: true }).catch(() => {});
  });

  const total = $derived(ui.step === 'open' ? ui.filled.length + ui.leftForUser.length : 0);
  const host = $derived(ui.step === 'open' ? new URL(ui.liveViewUrl).host : '');
</script>

<svelte:head><title>Fill it for me · {role.title} · JobScanr</title></svelte:head>

<section class="fillpane" aria-label="Fill it for me">
  <header class="livebar">
    <button class="btn sm" type="button" aria-label="Back to the role" onclick={back}>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 6l-6 6 6 6"></path></svg>
    </button>
    <div style="min-width: 0; flex: 1">
      <h1 class="one" style="margin: 0; font-size: 20px; font-weight: 800; letter-spacing: -0.02em; line-height: 1.2">{role.title}</h1>
      <div class="one" style="font-size: 14px; color: #9aa3b2">
        {role.company_name}{role.location ? ` · ${role.location}` : ''}{PLATFORM[role.ats_platform] ? ` · via ${PLATFORM[role.ats_platform]}` : ''}
      </div>
    </div>
    {#if ui.step !== 'open'}
      <span class="status-pill">
        <span class="dot" class:green={ui.step === 'done'} class:red={ui.step === 'error'} aria-hidden="true"></span>
        {ui.step === 'starting' ? 'Filling…' : ui.step === 'done' ? 'Applied' : 'Didn’t open'}
      </span>
    {/if}
  </header>

  {#if ui.step === 'starting'}
    <div class="enter workspace" role="status">
      <div class="browser" aria-hidden="true">
        <div class="chrome"><span class="one">{company} application form</span><span style="font-weight: 700; white-space: nowrap">Live view · you submit here</span></div>
        <div style="padding: 24px 32px 28px; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px">
          <span class="skel-light" style="grid-column: span 2; width: 55%; height: 20px"></span>
          {#each Array(6) as _, i (i)}<span class="skel-light" style="height: 38px"></span>{/each}
          <span class="skel-light" style="grid-column: span 2; height: 72px"></span>
        </div>
      </div>
      <aside class="helper">
        <div class="hcard">
          <h2 class="hhead">Setting up the form</h2>
          <ol class="steps">
            {#each STEPS as s, i (s)}
              <li class:done={i < progress} class:now={i === progress}>
                <span class="sicon" aria-hidden="true">
                  {#if i < progress}
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"></path></svg>
                  {:else if i === progress}<span class="spin"></span>{/if}
                </span>
                {s}
              </li>
            {/each}
          </ol>
        </div>
        <p class="hnote">This can take up to a minute. Leaving this page ends the session.</p>
      </aside>
    </div>
  {:else if ui.step === 'open'}
    <div class="enter workspace">
      <div style="flex: 999 1 520px; min-width: 0; display: flex; flex-direction: column; gap: 12px">
        {#if ui.captcha}
          <div role="status" class="banner">{role.company_name} is asking for a captcha. Solve it in the form below.</div>
        {/if}
        <div class="browser">
          <div class="chrome"><span class="one">{host}</span><span style="font-weight: 700; white-space: nowrap">Live view · you submit here</span></div>
          <iframe
            src={ui.liveViewUrl}
            title="{company} application form, for you to review and submit"
            sandbox="allow-same-origin allow-scripts"
            allow="clipboard-read; clipboard-write"
          ></iframe>
        </div>
      </div>
      <aside class="helper">
        <div class="hcard">
          <div style="display: flex; justify-content: space-between; align-items: baseline; gap: 12px">
            <h2 class="hhead">Filled for you</h2>
            {#if total}<span style="font-size: 14px; font-weight: 800">{ui.filled.length} of {total}</span>{/if}
          </div>
          {#if total}<div class="meter" aria-hidden="true"><span style="width: {Math.round((100 * ui.filled.length) / total)}%"></span></div>{/if}
          <p class="hnote">
            {ui.filled.length ? `${ui.filled.slice(0, 6).join(', ')}${ui.filled.length > 6 ? ' and more' : ''} are in.` : 'Your contact details and CV are in.'}
          </p>
        </div>
        {#if ui.leftForUser.length}
          <div class="hcard">
            <h2 class="hhead"><span class="dot amber" aria-hidden="true"></span>Needs you · {ui.leftForUser.length}</h2>
            <ul class="todo">
              {#each ui.leftForUser as label, i (i)}<li><span>{label}</span><span class="req">Required</span></li>{/each}
            </ul>
          </div>
        {/if}
        {#each ui.drafts as d, i (d.label)}
          <div class="hcard">
            <h2 class="hhead">Check before you submit</h2>
            <div style="display: flex; flex-direction: column; gap: 4px">
              <span style="font-size: 14px; font-weight: 800; line-height: 1.4">{d.label}</span>
              <span style="font-size: 12px; font-weight: 700; color: #9aa3b2">{d.busy ? 'Redrafting…' : d.redrafted ? 'Redrafted with your note' : 'Drafted from your CV'}</span>
            </div>
            <label for="draftNote{i}" style="font-size: 13px; font-weight: 700; color: #c9cfda">Add a fact or steer it (optional)</label>
            <textarea id="draftNote{i}" class="input" rows="3" maxlength="500" bind:value={d.note} placeholder="e.g. Mention the dashboards I built in my internship" style="min-height: 76px; font-size: 14px"></textarea>
            <button class="btn sm" type="button" onclick={() => redraft(d)} aria-busy={d.busy}>
              {#if d.busy}<span class="spin" aria-hidden="true"></span>{/if}
              <span>{d.busy ? 'Redrafting…' : d.redrafted ? 'Redraft again' : 'Redraft'}</span>
            </button>
            {#if d.error}<p class="formmsg" role="alert">{d.error}</p>{/if}
            <span style="font-size: 12px; line-height: 1.5; color: #9aa3b2">Only your CV and your note are used. The new text goes into the form.</span>
          </div>
        {/each}
        <p class="hnote">You press Submit in the form. When {role.company_name} shows its confirmation page, this role moves to Applied by itself.</p>
      </aside>
    </div>
  {:else if ui.step === 'done'}
    <div class="enter outcome" role="status">
      <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="#3ddc97" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"></circle><path d="M8 12.5l2.8 2.8L16.5 9.5"></path></svg>
      <h2 style="margin: 0; font-size: 26px; font-weight: 800">{ui.title}</h2>
      <p class="lead">{ui.text}</p>
      <div style="display: flex; gap: 10px; flex-wrap: wrap"><a class="btn btn-white" href="/inbox">Next role</a></div>
    </div>
  {:else}
    <div class="enter outcome" role="alert">
      <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="#ff7a7a" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9"></circle><path d="M12 7.5v5.5M12 16.5v.01"></path></svg>
      <h2 style="margin: 0; font-size: 26px; font-weight: 800">{ui.title ?? `${company} form didn’t open.`}</h2>
      <p class="lead">{ui.text}</p>
      <div style="display: flex; gap: 10px; flex-wrap: wrap">
        <a class="btn btn-white" href={role.url} target="_blank" rel="noopener noreferrer">Apply on {company} site</a>
        <button class="btn" type="button" onclick={start}>Try again</button>
      </div>
    </div>
  {/if}
</section>
