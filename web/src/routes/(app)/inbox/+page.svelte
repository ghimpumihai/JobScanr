<script lang="ts">
  // The Inbox (#141): Today and Applications in one list + detail. The open role lives in the URL (?role=),
  // so Back and refresh keep it open. Search and the platform filter run over the loaded tab.
  import { deserialize } from '$app/forms';
  import { goto, invalidateAll } from '$app/navigation';
  import { page } from '$app/state';
  import { tick } from 'svelte';
  import type { ApplicationRecord, ApplicationStatus } from '$lib/types';
  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();

  type Tab = 'inbox' | 'applied' | 'not_interested' | 'closed';
  const TABS: { id: Tab; label: string }[] = [
    { id: 'inbox', label: 'Inbox' },
    { id: 'applied', label: 'Applied' },
    { id: 'not_interested', label: 'Not interested' },
    { id: 'closed', label: 'Closed' }
  ];
  const PLATFORMS: Record<string, string> = {
    greenhouse: 'Greenhouse',
    lever: 'Lever',
    ashby: 'Ashby',
    workday: 'Workday',
    smartrecruiters: 'SmartRecruiters',
    teamtailor: 'Teamtailor',
    google: 'Google'
  };
  const FILLABLE = ['greenhouse', 'lever', 'ashby']; // the platforms remote fill supports (session.ts FORM_HOSTS)
  const EMPTY: Record<Tab, string> = {
    inbox: 'Your inbox is clear. New matches arrive after the 06:00 UTC scan.',
    applied: 'Roles you mark as applied appear here.',
    not_interested: 'Roles you pass on appear here.',
    closed: 'Postings the scanner no longer finds appear here.'
  };

  const tab = $derived(data.tab as Tab);
  const tabLabel = $derived(TABS.find((t) => t.id === tab)!.label);

  // ---------- list: search, platform filter, unread ----------
  let query = $state('');
  let platforms = $state<string[]>([]);
  let msOpen = $state(false);
  let opened = $state<Set<number>>(new Set()); // opened in this visit, before the next load
  const unread = (r: ApplicationRecord) => r.status === 'manual_apply' && !r.opened_at && !opened.has(r.id);

  const matchesQuery = (r: ApplicationRecord) => {
    const q = query.trim().toLowerCase();
    return !q || [r.company_name, r.title, r.location].some((v) => v.toLowerCase().includes(q));
  };
  const list = $derived(data.applications.filter((r) => matchesQuery(r) && (!platforms.length || platforms.includes(r.ats_platform))));
  const platformCounts = $derived(
    Object.keys(PLATFORMS)
      .map((p) => ({ id: p, n: data.applications.filter((r) => r.ats_platform === p && matchesQuery(r)).length }))
      .filter((p) => p.n > 0 || platforms.includes(p.id))
  );
  const msLabel = $derived(
    !platforms.length ? 'All platforms' : platforms.length <= 2 ? platforms.map((p) => PLATFORMS[p]).join(', ') : `${platforms.length} platforms`
  );
  const unreadCount = $derived(tab === 'inbox' ? data.applications.filter(unread).length : 0);

  const DAY = 86_400_000;
  const utcDay = (iso: string) => Math.floor(new Date(iso).getTime() / DAY);
  const fmt = (iso: string | null, opts: Intl.DateTimeFormatOptions = { day: 'numeric', month: 'short' }) =>
    iso ? new Date(iso).toLocaleDateString('en-GB', { ...opts, timeZone: 'UTC' }) : '';
  const groups = $derived.by(() => {
    if (tab !== 'inbox') return list.length ? [{ label: tabLabel, rows: list }] : [];
    const today = Math.floor(Date.now() / DAY);
    const out: { label: string; rows: ApplicationRecord[] }[] = [];
    for (const r of list) {
      const age = today - utcDay(r.added_at);
      const label =
        age <= 0
          ? `Today · ${fmt(r.added_at, { weekday: 'short', day: 'numeric', month: 'short' })}`
          : age === 1
            ? `Yesterday · ${fmt(r.added_at, { weekday: 'short', day: 'numeric', month: 'short' })}`
            : 'Earlier';
      const g = out.find((x) => x.label === label);
      if (g) g.rows.push(r);
      else out.push({ label, rows: [r] });
    }
    return out;
  });
  const meta = (r: ApplicationRecord) =>
    r.status === 'stale_closed'
      ? `May be closed · last seen ${fmt(r.last_seen_at)}`
      : r.status === 'manual_apply'
        ? (unread(r) ? 'New · ' : '') + (PLATFORMS[r.ats_platform] ?? r.ats_platform)
        : r.status === 'submitted'
          ? `Applied ${fmt(r.applied_at)}`
          : 'Not interested';

  // ---------- selection (URL) ----------
  const selId = $derived(Number(page.url.searchParams.get('role')) || null);
  const sel = $derived(data.applications.find((r) => r.id === selId) ?? null);
  const isPhone = () => window.matchMedia('(max-width: 760px)').matches;

  function href(params: { tab?: Tab; role?: number | null }) {
    const u = new URLSearchParams();
    const t = params.tab ?? tab;
    if (t !== 'inbox') u.set('tab', t);
    if (params.role) u.set('role', String(params.role));
    const s = u.toString();
    return `/inbox${s ? `?${s}` : ''}`;
  }

  function pick(r: ApplicationRecord) {
    goto(href({ role: r.id }), { noScroll: true, keepFocus: true });
  }
  function deselect() {
    goto(href({ role: null }), { noScroll: true, keepFocus: true });
  }

  // Opening a role clears its unread dot (stored, so it stays cleared on the next visit).
  $effect(() => {
    const r = sel;
    if (!r || !unread(r)) return;
    opened = new Set(opened).add(r.id);
    if (data.demo) return;
    const body = new FormData();
    body.set('id', String(r.id));
    void fetch('/inbox?/markOpened', { method: 'POST', body, headers: { 'x-sveltekit-action': 'true' } }).catch(() => {});
  });

  // ---------- description (live from the job board) ----------
  type Desc = { facts: { k: string; v: string }[]; blocks: ({ h: string } | { p: string } | { li: string[] })[] };
  let desc = $state<{ id: number; state: 'loading' | 'ready' | 'missing'; d?: Desc } | null>(null);
  let expanded = $state(false);
  let descTry = $state(0);
  const descId = $derived(sel?.id ?? null); // a reload keeps the same role: no refetch
  $effect(() => {
    const id = descId;
    void descTry;
    expanded = false;
    if (!id) return;
    desc = { id, state: 'loading' };
    const ctrl = new AbortController();
    fetch(`/inbox/description?id=${id}`, { signal: ctrl.signal })
      .then(async (res) => {
        if (!res.ok) throw new Error();
        desc = { id, state: 'ready', d: await res.json() };
      })
      .catch(() => {
        if (!ctrl.signal.aborted) desc = { id, state: 'missing' };
      });
    return () => ctrl.abort();
  });

  // ---------- copy your details ----------
  let copied = $state<string | null>(null);
  let copyTimer: ReturnType<typeof setTimeout>;
  const fields = $derived(
    (
      [
        ['Name', data.profile?.full_name],
        ['Email', data.profile?.email],
        ['Phone', data.profile?.phone],
        ['Location', data.profile?.location],
        ['LinkedIn', data.profile?.linkedin],
        ['GitHub', data.profile?.github],
        ['Portfolio', data.profile?.portfolio]
      ] as [string, string | undefined][]
    ).filter((f): f is [string, string] => Boolean(f[1]))
  );
  let copyMsg = $state('');
  async function copy(label: string, value: string) {
    clearTimeout(copyTimer);
    try {
      await navigator.clipboard.writeText(value);
      copied = label;
      copyMsg = `${label} copied to your clipboard`;
    } catch {
      copied = null;
      copyMsg = `Could not copy ${label}. Select the text and copy it instead.`;
    }
    copyTimer = setTimeout(() => ((copied = null), (copyMsg = '')), 1600);
  }

  // ---------- status changes + undo ----------
  type Toast = { text: string; error?: boolean; undo?: { id: number; from: ApplicationStatus; to: ApplicationStatus } | null };
  let toast = $state<Toast | null>(null);
  let toastTimer: ReturnType<typeof setTimeout>;
  let busy = $state(false);
  function showToast(t: Toast) {
    clearTimeout(toastTimer);
    toast = t;
    toastTimer = setTimeout(() => (toast = null), 4000);
  }

  async function post(action: string, fields: Record<string, string>) {
    const body = new FormData();
    for (const [k, v] of Object.entries(fields)) body.set(k, v);
    const res = await fetch(`/inbox?/${action}`, { method: 'POST', body, headers: { 'x-sveltekit-action': 'true' } });
    return deserialize(await res.text());
  }

  async function setStatus(r: ApplicationRecord, to: ApplicationStatus) {
    if (busy) return;
    busy = true;
    const next = list[list.indexOf(r) + 1] ?? list[list.indexOf(r) - 1] ?? null;
    try {
      const result = await post('setStatus', { id: String(r.id), from: r.status, to });
      if (result.type === 'success') {
        const d = result.data as { message: string; undo: Toast['undo'] };
        showToast({ text: data.demo ? d.message : `${r.company_name} · ${r.title} ${d.message}`, undo: d.undo });
        // The next role opens on desktop; on phone the list comes back.
        await goto(href({ role: next && !isPhone() ? next.id : null }), { noScroll: true, keepFocus: true, invalidateAll: true });
      } else {
        const error = result.type === 'failure' ? String(result.data?.error ?? '') : '';
        showToast({ text: error || 'Could not change this role. Please try again.', error: true });
        if (result.type === 'failure' && result.status === 409) await invalidateAll();
      }
    } catch {
      showToast({ text: 'The connection failed. Reload to see this role.', error: true });
    } finally {
      busy = false;
    }
  }

  async function undo() {
    const u = toast?.undo;
    if (!u) return;
    clearTimeout(toastTimer);
    toast = null;
    const result = await post('setStatus', { id: String(u.id), from: u.from, to: u.to }).catch(() => null);
    if (result?.type === 'success') {
      await goto(href({ tab: 'inbox', role: isPhone() ? null : u.id }), { noScroll: true, invalidateAll: true });
    } else {
      showToast({ text: 'Could not undo. Find the role in its tab and move it back.', error: true });
    }
  }

  // ---------- fill it for me: consent popup ----------
  let consentFor = $state<ApplicationRecord | null>(null);
  let consentTrigger: HTMLElement | null = null;
  const canFill = $derived(Boolean(sel && data.remoteApply && sel.status === 'manual_apply' && FILLABLE.includes(sel.ats_platform)));
  function openConsent(e: MouseEvent) {
    consentTrigger = e.currentTarget as HTMLElement;
    consentFor = sel;
  }
  async function closeConsent() {
    consentFor = null;
    await tick();
    consentTrigger?.focus();
  }
  function dialog(node: HTMLElement) {
    node.querySelector<HTMLElement>('button:not([disabled])')?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') return void closeConsent();
      if (e.key !== 'Tab') return;
      const items = [...node.querySelectorAll<HTMLElement>('a[href], button:not([disabled])')];
      const first = items[0];
      const last = items.at(-1);
      if (e.shiftKey && document.activeElement === first) (e.preventDefault(), last?.focus());
      else if (!e.shiftKey && document.activeElement === last) (e.preventDefault(), first?.focus());
    };
    node.addEventListener('keydown', onKey);
    return () => node.removeEventListener('keydown', onKey);
  }

  const companyPossessive = (name: string) => `${name}’${name.endsWith('s') ? '' : 's'}`;
</script>

<svelte:head><title>{tabLabel} · JobScanr</title></svelte:head>

<section class="list" aria-labelledby="inboxTitle">
  <header class="list-head">
    <div>
      <h1 class="title" id="inboxTitle">{tabLabel}</h1>
      <p class="subline">
        {#if tab !== 'inbox'}
          You apply on each employer’s site. JobScanr never submits for you.
        {:else if unreadCount}
          {unreadCount} new since your last visit · roles stay here until you decide
        {:else}
          Nothing new since your last visit · next scan 06:00 UTC
        {/if}
      </p>
      <p class="scan-m">Scanned daily at 06:00 UTC</p>
    </div>
    <div role="tablist" aria-label="Status" class="tablist" style="display: flex; gap: 6px; flex-wrap: wrap">
      {#each TABS as t (t.id)}
        <a class="tab" role="tab" aria-selected={t.id === tab} href={href({ tab: t.id, role: null })} data-sveltekit-noscroll>
          {t.label} <span class="n">{data.counts[t.id]}</span>
        </a>
      {/each}
    </div>
    <div class="filters">
      <label class="search">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"></circle><path d="M20 20l-3.5-3.5"></path></svg>
        <input class="input" type="search" bind:value={query} aria-label="Search your roles by company, job title or city" placeholder="Company, job title or city" />
      </label>
      <div class="ms">
        <button class="input picker" type="button" aria-haspopup="true" aria-expanded={msOpen} aria-label="Filter by job board platform: {msLabel}" onclick={() => (msOpen = !msOpen)}>
          <span class="one" style="display: block">{msLabel}</span>
        </button>
        {#if msOpen}
          <button class="ms-scrim" type="button" aria-label="Close platform filter" onclick={() => (msOpen = false)}></button>
          <div class="ms-pop" role="group" aria-label="Platforms">
            {#each platformCounts as p (p.id)}
              <label class="ms-opt">
                <input
                  class="ms-box"
                  type="checkbox"
                  checked={platforms.includes(p.id)}
                  onchange={() => (platforms = platforms.includes(p.id) ? platforms.filter((x) => x !== p.id) : [...platforms, p.id])}
                />
                <span style="flex: 1">{PLATFORMS[p.id]}</span><span class="ms-n">{p.n}</span>
              </label>
            {:else}
              <p class="ms-n" style="margin: 0; padding: 10px">No roles in this tab.</p>
            {/each}
            <div class="ms-foot">
              <button class="ms-clear" type="button" onclick={() => (platforms = [])}>Clear</button>
              <button class="btn btn-white sm" type="button" onclick={() => (msOpen = false)}>Done</button>
            </div>
          </div>
        {/if}
      </div>
    </div>
  </header>

  {#if data.loadError}
    <div class="empty" role="alert" style="display: flex; flex-direction: column; gap: 12px; align-items: flex-start">
      <strong style="color: #ffffff; font-size: 18px">Your inbox didn’t load.</strong>
      <span>The morning scan itself is fine; your roles just didn’t reach the page. Nothing you marked is lost.</span>
      <button class="btn" type="button" onclick={() => invalidateAll()}>Reload</button>
    </div>
  {:else}
    {#each groups as g, gi (g.label)}
      <h2 class="group">{g.label}</h2>
      <ul class="rows">
        {#each g.rows as r, i (r.id)}
          <li class="stag" style="animation-delay: {Math.min(40 * (i + gi * 3), 400)}ms">
            <a
              class="row irow"
              class:is-sel={r.id === selId}
              class:unread={unread(r)}
              href={href({ role: r.id })}
              aria-current={r.id === selId ? 'true' : undefined}
              data-sveltekit-noscroll
              data-sveltekit-keepfocus
              onclick={(e) => {
                if (e.metaKey || e.ctrlKey || e.shiftKey) return;
                e.preventDefault();
                pick(r);
              }}
            >
              <span class="dot" class:white={unread(r)} class:none={!unread(r)}><span class="sr-only">{unread(r) ? 'New' : ''}</span></span>
              <span class="irow-body">
                <span class="clamp irow-title">{r.title}</span>
                <span class="one">{r.company_name}{r.location ? ` · ${r.location}` : ''}</span>
                <span class="irow-meta">
                  <span class="one" style={r.status === 'stale_closed' ? 'color: #f5b84a' : ''}>{meta(r)}</span>
                  <span class="pay" class:none={!r.compensation} title={r.compensation || undefined}>{r.compensation || "Salary not listed"}</span>
                </span>
              </span>
            </a>
          </li>
        {/each}
      </ul>
    {/each}
    {#if !list.length}
      <p class="empty">
        {platforms.length && data.applications.length
          ? `No roles from ${platforms.length === 1 ? PLATFORMS[platforms[0]] : 'these platforms'} in this tab.`
          : query.trim() && data.applications.length
            ? `No roles match “${query.trim()}” in this tab.`
            : EMPTY[tab]}
      </p>
    {/if}
  {/if}
</section>

<section class="detail" aria-label="Selected role">
  {#if sel}
    {#key sel.id}
      <button class="close-x" type="button" onclick={deselect} aria-label="Close this role" title="Close">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"></path></svg>
      </button>
      <div class="detail-inner enter">
        <button class="btn back" type="button" onclick={deselect} style="align-self: flex-start">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 6l-6 6 6 6"></path></svg>
          {tabLabel}
        </button>
        <header style="display: flex; flex-direction: column; gap: 10px">
          <div class="role-company">{sel.company_name}{sel.location ? ` · ${sel.location}` : ''}</div>
          <h2 class="role-title">{sel.title}</h2>
          <div class="role-pay" class:none={!sel.compensation}>{sel.compensation || 'Salary not listed'}</div>
          {#if sel.matched.length}
            <div style="display: flex; gap: 6px; flex-wrap: wrap; align-items: center">
              <span style="font-size: 13px; color: #9aa3b2; margin-right: 4px">Matched on</span>
              {#each sel.matched as m (m)}<span class="chip">{m}</span>{/each}
            </div>
          {/if}
        </header>

        {#if sel.status === 'stale_closed'}
          <div class="note" role="status">
            Our scanner last saw this posting on {fmt(sel.last_seen_at, { day: 'numeric', month: 'short', year: 'numeric' })}. It is probably
            closed, but the link may still work.
          </div>
        {/if}

        <section class="about" aria-labelledby="aboutHead" aria-busy={desc?.state === 'loading'}>
          <div class="about-head">
            <h3 id="aboutHead" class="step">About the role</h3>
            <span class="about-src">{desc?.state === 'missing' ? 'Not available' : `From ${companyPossessive(sel.company_name)} job post`}</span>
          </div>
          {#if desc?.id === sel.id && desc.state === 'ready' && desc.d}
            <div class="enter" style="display: flex; flex-direction: column; gap: 12px">
              {#if desc.d.facts.length}
                <dl class="facts">
                  {#each desc.d.facts as x (x.k)}<div><dt>{x.k}</dt><dd>{x.v}</dd></div>{/each}
                </dl>
              {/if}
              <div class="desc" class:is-clamped={!expanded}>
                {#each desc.d.blocks as b, i (i)}
                  {#if 'h' in b}<h4>{b.h}</h4>
                  {:else if 'p' in b}<p>{b.p}</p>
                  {:else}<ul>{#each b.li as it, j (j)}<li>{it}</li>{/each}</ul>{/if}
                {/each}
              </div>
              <button class="linkbtn" type="button" aria-expanded={expanded} onclick={() => (expanded = !expanded)}>
                {expanded ? 'Show less' : 'Show full description'}
              </button>
            </div>
          {:else if desc?.id === sel.id && desc.state === 'missing'}
            <div class="missing" role="status">
              <p>We couldn’t load the description from {companyPossessive(sel.company_name)} site just now. You can read it there instead.</p>
              <div style="display: flex; gap: 10px; flex-wrap: wrap">
                <button class="btn" type="button" onclick={() => descTry++}>Try again</button>
                <a class="btn" href={sel.url} target="_blank" rel="noopener noreferrer">View the posting on {companyPossessive(sel.company_name)} site</a>
              </div>
            </div>
          {:else}
            <div role="status" aria-label="Loading the description" style="display: flex; flex-direction: column; gap: 10px; padding: 4px 0 6px">
              <span class="skel" style="width: 46%"></span><span class="skel" style="width: 92%"></span><span class="skel" style="width: 86%"></span><span class="skel" style="width: 64%"></span>
            </div>
          {/if}
        </section>

        {#if sel.status === 'manual_apply'}
          <section style="display: flex; flex-direction: column; gap: 10px">
            <h3 class="step">1 · Open the posting</h3>
            <div style="display: flex; gap: 10px; flex-wrap: wrap">
              <a class="btn btn-white" href={sel.url} target="_blank" rel="noopener noreferrer">
                Apply on {companyPossessive(sel.company_name)} site
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 4h6v6"></path><path d="M20 4l-9 9"></path><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"></path></svg>
              </a>
              {#if canFill}
                <button class="btn" type="button" onclick={openConsent}>Or let JobScanr fill the form (trial)</button>
              {/if}
            </div>
          </section>
          {#if fields.length}
            <section style="display: flex; flex-direction: column; gap: 10px">
              <h3 class="step">2 · Copy your details</h3>
              <dl class="details">
                {#each fields as [label, value] (label)}
                  <div>
                    <div style="min-width: 0"><dt>{label}</dt><dd>{value}</dd></div>
                    <button type="button" class="copy" class:is-done={copied === label} onclick={() => copy(label, value)} aria-label="Copy {label}">
                      {#if copied === label}
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"></path></svg>Copied
                      {:else}Copy{/if}
                    </button>
                  </div>
                {/each}
              </dl>
              <p aria-live="polite" class="copied-msg">{copyMsg}</p>
            </section>
          {/if}
          <section style="display: flex; flex-direction: column; gap: 10px; padding-bottom: 24px">
            <h3 class="step">3 · Attach your CV</h3>
            {#if data.profile?.resume_filename}
              <form method="POST" action="/settings?/downloadCv">
                <button type="submit" class="btn">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"></path></svg>
                  Download {data.profile.resume_filename}
                </button>
              </form>
            {:else}
              <p class="help">No CV yet. <a href="/settings?section=details">Upload one in Settings</a>.</p>
            {/if}
          </section>
        {:else}
          <dl class="status-dl">
            <div>
              <dt>Status</dt>
              <dd style="color: {sel.status === 'submitted' ? '#3ddc97' : sel.status === 'stale_closed' ? '#f5b84a' : '#c9cfda'}">
                {sel.status === 'submitted' ? 'Applied' : sel.status === 'stale_closed' ? 'Probably closed' : 'Not interested'}
              </dd>
            </div>
            {#if sel.status === 'submitted' && sel.applied_at}
              <div><dt>Marked</dt><dd>{fmt(sel.applied_at, { day: 'numeric', month: 'short', year: 'numeric' })}</dd></div>
            {/if}
          </dl>
          <a class="btn" href={sel.url} target="_blank" rel="noopener noreferrer" style="align-self: flex-start; margin-bottom: 24px">
            View the posting on {companyPossessive(sel.company_name)} site
          </a>
        {/if}
      </div>
      <div class="actions">
        {#if sel.status === 'manual_apply' || sel.status === 'stale_closed'}
          <button type="button" class="btn" disabled={busy} onclick={() => setStatus(sel!, 'dismissed')}>Not interested</button>
          <button type="button" class="btn btn-white" disabled={busy} onclick={() => setStatus(sel!, 'submitted')}>I applied</button>
        {:else}
          <button type="button" class="btn" disabled={busy} onclick={() => setStatus(sel!, 'manual_apply')}>Move back to Inbox</button>
        {/if}
      </div>
    {/key}
  {:else}
    <div class="noRole enter">
      <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#4a505c" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 13l2.5-7h11L20 13v6H4z"></path><path d="M4 13h5l1 2h4l1-2h5"></path></svg>
      {#if data.loadError}
        <h2>Something went wrong</h2>
        <p>If it keeps happening, check your connection and try again in a minute.</p>
      {:else if !data.applications.length}
        <h2>{tab === 'inbox' ? 'You’re all caught up.' : 'Nothing here yet.'}</h2>
        <p>{tab === 'inbox' ? 'Every role has a decision. Next scan at 06:00 UTC; new matches land here.' : EMPTY[tab]}</p>
      {:else}
        <h2>Pick a role to see the details</h2>
        <p>
          {#if tab !== 'inbox'}Choose a role on the left to see its status.
          {:else if unreadCount}{unreadCount} new since your last visit, {data.applications.length} waiting in total. Open one to read about it and apply.
          {:else}{data.applications.length} {data.applications.length === 1 ? 'role' : 'roles'} waiting for a decision.{/if}
        </p>
      {/if}
    </div>
  {/if}
</section>

{#if toast}
  <div class="toast toast-box" class:error={toast.error} role="status" aria-live="polite">
    {#if !toast.error}<span class="toast-timer" aria-hidden="true"></span>{/if}
    <span style="flex: 1">{toast.text}</span>
    {#if toast.undo}<button type="button" class="toast-undo" onclick={undo}>Undo</button>{/if}
    <button type="button" class="toast-x" aria-label="Dismiss message" onclick={() => (toast = null)}>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"></path></svg>
    </button>
  </div>
{/if}

{#if consentFor}
  <button class="modal-scrim" type="button" aria-label="Close" tabindex="-1" onclick={closeConsent}></button>
  <div class="modal" role="dialog" aria-modal="true" aria-labelledby="consentTitle" {@attach dialog}>
    <div class="modal-head">
      <h2 id="consentTitle">Let JobScanr fill {companyPossessive(consentFor.company_name)} form?</h2>
      <button class="modal-x" type="button" aria-label="Close" onclick={closeConsent}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"></path></svg>
      </button>
    </div>
    <dl class="consent">
      <div><dt>What’s shared</dt><dd>Your name, contact details, links, education, CV and any equal-opportunity answers you saved, for this one application.</dd></div>
      <div><dt>Who runs it</dt><dd>A browser run by {data.remoteProvider}, a third-party service.</dd></div>
      <div><dt>How long</dt><dd>Until you leave the form, or 13 minutes at most. Up to 5 fills a day.</dd></div>
      <div><dt>Who submits</dt><dd class="strong">You do. JobScanr never presses Submit; check every answer first.</dd></div>
    </dl>
    <div class="modal-foot">
      <span class="fills">{data.fillsLeft > 0 ? `${data.fillsLeft} of 5 fills left today` : 'No fills left today. They reset at midnight UTC.'}</span>
      <button class="btn" type="button" onclick={closeConsent}>Cancel</button>
      {#if data.fillsLeft > 0}
        <a class="btn btn-white" href="/inbox/fill?role={consentFor.id}">I agree, start</a>
      {:else}
        <button class="btn btn-white" type="button" disabled>I agree, start</button>
      {/if}
    </div>
  </div>
{/if}
