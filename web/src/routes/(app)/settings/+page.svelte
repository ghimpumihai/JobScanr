<script lang="ts">
  // Settings in sections (#141). The open section lives in the URL (?section=), so links and refresh keep it.
  import { deserialize } from '$app/forms';
  import { beforeNavigate, goto, invalidateAll } from '$app/navigation';
  import { page } from '$app/state';
  import { DEGREES, EEO_FIELDS } from '$lib/eeo';
  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();

  const ALL_SENIORITY_LEVELS = [
    'Internship / Working Student',
    'Graduate / New Grad',
    'Entry Level (0-1 yrs)',
    'Junior (1-2 yrs)',
    'Associate (2-3 yrs)',
    'Mid-Level (3-5 yrs)',
    'Senior (5-8 yrs)',
    'Lead / Principal (8+ yrs)'
  ];
  const EEO_LABELS: Record<keyof typeof EEO_FIELDS, string> = {
    gender: 'Gender',
    race: 'Race or ethnicity',
    veteran: 'Veteran status',
    disability: 'Disability'
  };

  type Section = 'search' | 'details' | 'eeo' | 'matching' | 'answers' | 'drafts' | 'account';
  const IDS: Section[] = ['search', 'details', 'eeo', 'matching', 'answers', 'drafts', 'account'];
  const section = $derived<Section>(IDS.find((s) => s === page.url.searchParams.get('section')) ?? 'search');

  // Form fields: seeded once, so a save never overwrites edits in progress with what the server echoes back.
  // svelte-ignore state_referenced_locally
  const profile = data.profile;
  let levels = $state<string[]>([...(profile?.seniority_levels ?? [])]);
  let locations = $state<string[]>([...(profile?.preferred_locations ?? [])]);
  let titles = $state<string[]>([...(profile?.target_keywords ?? [])]);
  let skips = $state<string[]>([...(profile?.excluded_keywords ?? [])]);
  let mode = $state(profile?.auto_apply_mode === 'disabled' ? 'disabled' : 'approval_required');
  let drafts = $state(profile?.llm_drafts_enabled ?? false);
  let eeo = $state<Record<string, string>>({
    gender: profile?.eeo?.gender ?? 'prefer_not',
    race: profile?.eeo?.race ?? 'prefer_not',
    veteran: profile?.eeo?.veteran ?? 'prefer_not',
    disability: profile?.eeo?.disability ?? 'prefer_not'
  });
  const openAnswers = $derived((data.answers ?? []).filter((a) => !a.answer?.trim()).length);
  const savedMode = $derived(data.profile?.auto_apply_mode === 'disabled' ? 'disabled' : 'approval_required');

  const sections = $derived<{ id: Section; label: string; note?: string; warn?: boolean }[]>([
    { id: 'search', label: 'What to look for' },
    { id: 'details', label: 'Your details' },
    { id: 'eeo', label: 'Equal opportunity', note: 'Optional' },
    { id: 'matching', label: 'Daily matching', note: savedMode === 'disabled' ? 'Paused' : 'On', warn: savedMode === 'disabled' },
    { id: 'answers', label: 'Saved answers', note: openAnswers ? `${openAnswers} open` : undefined },
    { id: 'drafts', label: 'Drafted answers', note: data.profile?.llm_drafts_enabled ? 'On' : 'Off' },
    { id: 'account', label: 'Account' }
  ]);

  // ---------- unsaved changes ----------
  let dirty = $state(false);
  const LEAVE = 'You have unsaved changes in this section. Leave without saving?';
  function pick(id: Section) {
    if (id === section) return;
    if (dirty && !confirm(LEAVE)) return;
    dirty = false;
    msg = null;
    goto(`/settings?section=${id}`, { noScroll: true, keepFocus: true, replaceState: true });
  }
  beforeNavigate((nav) => {
    if (dirty && nav.to?.url.pathname !== '/settings' && !confirm(LEAVE)) nav.cancel();
  });

  // ---------- saving: Saving… → Saved, the button keeps its size ----------
  let saving = $state<string | null>(null);
  let saved = $state<string | null>(null);
  let msg = $state<{ text: string; error: boolean } | null>(null);
  let savedTimer: ReturnType<typeof setTimeout>;

  async function post(action: string, body: FormData) {
    const res = await fetch(`/settings?/${action}`, { method: 'POST', body, headers: { 'x-sveltekit-action': 'true' } });
    return deserialize(await res.text());
  }

  /** Posts the form to each action in turn; stops at the first failure. */
  async function save(key: string, actions: string[], body: FormData) {
    if (saving) return;
    saving = key;
    saved = null;
    msg = null;
    try {
      for (const action of actions) {
        const result = await post(action, body);
        if (result.type !== 'success') {
          const error = result.type === 'failure' ? String(result.data?.error ?? '') : '';
          msg = { text: error || 'The request failed. Check your connection and try again.', error: true };
          return;
        }
        msg = { text: String(result.data?.message ?? 'Saved.'), error: false };
      }
      dirty = false;
      saved = key;
      clearTimeout(savedTimer);
      savedTimer = setTimeout(() => (saved = null), 2000);
      await invalidateAll();
    } catch {
      msg = { text: 'The request failed. Check your connection and try again.', error: true };
    } finally {
      saving = null;
    }
  }
  function submitForm(key: string, ...actions: string[]) {
    return (e: SubmitEvent) => {
      e.preventDefault();
      void save(key, actions, new FormData(e.currentTarget as HTMLFormElement));
    };
  }
  function saveFields(key: string, action: string, fields: Record<string, string>) {
    const body = new FormData();
    for (const [k, v] of Object.entries(fields)) body.set(k, v);
    void save(key, [action], body);
  }

  // ---------- tag lists ----------
  let newItem = $state<Record<string, string>>({ loc: '', kw: '', ex: '' });
  function addTo(list: string[], key: string): string[] {
    const v = newItem[key].trim();
    newItem[key] = '';
    dirty = true;
    return v && !list.some((x) => x.toLowerCase() === v.toLowerCase()) ? [...list, v] : list;
  }

  // ---------- CV ----------
  let cvInput = $state<HTMLInputElement>();
  let cvForm = $state<HTMLFormElement>();
  let dragging = $state(false);
  function dropCv(e: DragEvent) {
    e.preventDefault();
    dragging = false;
    if (!e.dataTransfer?.files.length || !cvInput) return;
    cvInput.files = e.dataTransfer.files;
    cvForm?.requestSubmit();
  }
  const kb = (n?: number) => (n ? ` · ${n} KB` : '');
</script>

<svelte:head><title>Settings · JobScanr</title></svelte:head>

{#snippet saveButton(key: string, label: string, sm = false)}
  <button class="btn btn-white save" class:sm class:is-saving={saving === key} class:is-saved={saved === key} type="submit" disabled={data.loadError}>
    {#if saving === key}
      <span class="spin dark" aria-hidden="true"></span><span>Saving…</span>
    {:else if saved === key}
      <svg class="tick" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"></path></svg><span>Saved</span>
    {:else}<span>{label}</span>{/if}
  </button>
{/snippet}

{#snippet tagList(list: string[], remove: (v: string) => void)}
  {#if list.length}
    <div class="tags">
      {#each list as item (item)}
        <span class="tag">
          {item}
          <button type="button" aria-label="Remove {item}" onclick={() => remove(item)}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"></path></svg>
          </button>
        </span>
      {/each}
    </div>
  {/if}
{/snippet}

{#snippet adder(key: string, id: string, placeholder: string, add: () => void)}
  <div style="display: flex; gap: 8px; max-width: 440px">
    <input {id} class="input" {placeholder} maxlength="60" bind:value={newItem[key]} onkeydown={(e) => e.key === 'Enter' && (e.preventDefault(), add())} />
    <button class="btn" type="button" onclick={add}>Add</button>
  </div>
{/snippet}

<main class="smain">
  <div style="flex: 1 1 100%"><h1 class="title">Settings</h1></div>

  <div class="secs" role="tablist" aria-label="Settings sections">
    {#each sections as s (s.id)}
      <button class="sec" type="button" role="tab" aria-selected={s.id === section} onclick={() => pick(s.id)}>
        <span>{s.label}</span>
        {#if s.note}<span style="font-size: 12px; color: {s.warn ? '#ff7a7a' : '#9aa3b2'}">{s.note}</span>{/if}
      </button>
    {/each}
  </div>

  <div class="panel" role="tabpanel" tabindex="-1" aria-label={sections.find((s) => s.id === section)?.label} oninput={() => (dirty = true)}>
    {#if data.loadError}
      <div class="alert" role="alert" style="margin-bottom: 20px">Could not load your settings. Saving is off so nothing gets overwritten. Please reload.</div>
    {/if}

    {#key section}
      <div class="enter">
        {#if section === 'search'}
          <h2>What to look for</h2>
          <p class="panel-lead">Every morning’s scan keeps only the roles that pass these filters, across 3,600+ company job boards.</p>
          <form onsubmit={submitForm('search', 'savePreferences')} style="margin-top: 20px">
            <input type="hidden" name="seniorityLevels" value={JSON.stringify(levels)} />
            <input type="hidden" name="locations" value={JSON.stringify(locations)} />
            <input type="hidden" name="targetKeywords" value={JSON.stringify(titles)} />
            <input type="hidden" name="excludedKeywords" value={JSON.stringify(skips)} />
            <div class="block">
              <span class="lbl">Seniority</span>
              <div class="pills">
                {#each ALL_SENIORITY_LEVELS as level (level)}
                  <button
                    class="pill"
                    type="button"
                    aria-pressed={levels.includes(level)}
                    onclick={() => ((levels = levels.includes(level) ? levels.filter((l) => l !== level) : [...levels, level]), (dirty = true))}
                  >{level}</button>
                {/each}
              </div>
            </div>
            <div class="block">
              <label class="lbl" for="loc">Locations</label>
              {@render tagList(locations, (v) => ((locations = locations.filter((x) => x !== v)), (dirty = true)))}
              {@render adder('loc', 'loc', 'Add a city, e.g. Zurich', () => (locations = addTo(locations, 'loc')))}
            </div>
            <div class="block">
              <label class="lbl" for="kw">Titles to look for</label>
              <p class="help">Roles whose titles contain these come first.</p>
              {@render tagList(titles, (v) => ((titles = titles.filter((x) => x !== v)), (dirty = true)))}
              {@render adder('kw', 'kw', 'e.g. Python, Go', () => (titles = addTo(titles, 'kw')))}
            </div>
            <div class="block">
              <label class="lbl" for="ex">Titles to skip</label>
              <p class="help">Roles whose titles contain these never reach your Inbox.</p>
              {@render tagList(skips, (v) => ((skips = skips.filter((x) => x !== v)), (dirty = true)))}
              {@render adder('ex', 'ex', 'e.g. Rust, Staff', () => (skips = addTo(skips, 'ex')))}
            </div>
            <div style="display: flex; justify-content: flex-end; padding-top: 20px; border-top: 1px solid #1d2026">
              {@render saveButton('search', 'Save search')}
            </div>
          </form>
        {:else if section === 'details'}
          <h2>Your details</h2>
          <p class="panel-lead">Everything an employer gets from you: copy it when you apply, or let Fill it for me type it in.</p>
          <section class="block" style="margin-top: 20px" aria-labelledby="cvHead">
            <h3 id="cvHead" class="lbl" style="margin: 0">CV</h3>
            <p class="help">The exact file you upload is the one employers receive.</p>
            {#if data.profile?.resume_filename}
              <div style="display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; padding: 20px; border-radius: 16px; background: #15171c; border: 1px solid #2a2e37">
                <div style="display: flex; gap: 14px; align-items: center; min-width: 0">
                  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#c9cfda" stroke-width="1.6" stroke-linejoin="round" aria-hidden="true"><path d="M7 3h7l5 5v13H7z"></path><path d="M14 3v5h5"></path></svg>
                  <div style="min-width: 0">
                    <div class="one" style="font-size: 16px; font-weight: 800">{data.profile.resume_filename}</div>
                    <div style="font-size: 14px; color: #9aa3b2">Uploaded {data.profile.resume_uploaded_at ?? ''}{kb(data.profile.resume_size_kb)}</div>
                  </div>
                </div>
                <form method="POST" action="?/downloadCv"><button class="btn" type="submit">Download</button></form>
              </div>
            {/if}
            <form bind:this={cvForm} onsubmit={submitForm('cv', 'uploadCv')} enctype="multipart/form-data">
              <label
                class="drop"
                for="cvfile"
                style={dragging ? 'border-color: #ffffff' : ''}
                ondragover={(e) => (e.preventDefault(), (dragging = true))}
                ondragleave={() => (dragging = false)}
                ondrop={dropCv}
              >
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#c9cfda" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 15V4M7 9l5-5 5 5"></path><path d="M5 15v4a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-4"></path></svg>
                <span style="font-size: 16px; font-weight: 800; color: #ffffff">
                  {saving === 'cv' ? 'Uploading…' : saved === 'cv' ? 'Uploaded' : data.profile?.resume_filename ? 'Replace your CV' : 'Upload your CV'}
                </span>
                <span class="help" style="max-width: none">Drag a file here, or choose one. PDF, DOCX or DOC, up to 2 MB.</span>
                <span class="btn" aria-hidden="true" style="margin-top: 6px">Choose a file</span>
                <input bind:this={cvInput} id="cvfile" name="cv" class="sr-only" type="file" accept=".pdf,.docx,.doc" onchange={() => cvForm?.requestSubmit()} />
              </label>
            </form>
          </section>

          <form onsubmit={submitForm('details', 'savePreferences', 'saveEducation')}>
            <div class="block">
              <h3 class="lbl" style="margin: 0">Contact and profile</h3>
              <div class="two">
                <label class="field">First and last name<input class="input" name="fullName" autocomplete="name" value={profile?.full_name ?? ''} /></label>
                <label class="field">Email (from your Google account)<input class="input" value={profile?.email ?? ''} readonly /></label>
                <label class="field">Phone<input class="input" name="phone" type="tel" autocomplete="tel" value={profile?.phone ?? ''} /></label>
                <label class="field">Where you live now<input class="input" name="location" value={profile?.location ?? ''} /></label>
                <label class="field">LinkedIn<input class="input" name="linkedin" type="url" placeholder="https://" value={profile?.linkedin ?? ''} /></label>
                <label class="field">GitHub<input class="input" name="github" type="url" placeholder="https://" value={profile?.github ?? ''} /></label>
                <label class="field">Portfolio<input class="input" name="portfolio" type="url" placeholder="https://" value={profile?.portfolio ?? ''} /></label>
                <label class="field">Years of experience<input class="input" name="yearsExperience" type="number" min="0" max="50" value={profile?.years_experience ?? ''} /></label>
                <label class="field">Notice period (days)<input class="input" name="noticePeriodDays" type="number" min="0" max="365" value={profile?.notice_period_days ?? ''} /></label>
                <label class="field">Allowed to work in your target countries?
                  <select class="input select" name="workAuth" value={profile?.work_authorization ?? ''}>
                    <option value="">Not set</option><option value="yes">Yes</option><option value="no">No</option>
                  </select>
                </label>
                <label class="field">Need visa sponsorship, now or later?
                  <select class="input select" name="requiresSponsorship" value={profile?.requires_sponsorship ?? ''}>
                    <option value="">Not set</option><option value="no">No</option><option value="yes">Yes</option>
                  </select>
                </label>
              </div>
            </div>
            <div class="block">
              <h3 class="lbl" style="margin: 0">Education</h3>
              <p class="help">Your highest degree. Fill it for me picks the matching school and degree in the form’s lists.</p>
              <div class="two">
                <label class="field">School or university<input class="input" name="school" maxlength="120" value={profile?.education?.school ?? ''} /></label>
                <label class="field">Degree
                  <select class="input select" name="degree" value={profile?.education?.degree ?? ''}>
                    <option value="">Not set</option>
                    {#each DEGREES as d (d.value)}<option value={d.value}>{d.label}</option>{/each}
                  </select>
                </label>
                <label class="field">Field of study<input class="input" name="fieldOfStudy" maxlength="120" value={profile?.education?.field_of_study ?? ''} /></label>
                <label class="field">Graduation year<input class="input" name="graduationYear" type="number" min="1950" max="2100" value={profile?.education?.graduation_year ?? ''} /></label>
              </div>
            </div>
            <div style="display: flex; justify-content: flex-end; padding-top: 20px; border-top: 1px solid #1d2026">
              {@render saveButton('details', 'Save details')}
            </div>
          </form>
        {:else if section === 'eeo'}
          <h2>Equal opportunity</h2>
          <p class="panel-lead">
            Many US employers ask these voluntary questions at the end of the form. Fill it for me picks your answer; left at
            “Prefer not to say”, it picks the form’s decline option. These answers are only used to fill forms, and you can clear
            them at any time.
          </p>
          <form onsubmit={submitForm('eeo', 'saveEeo')}>
            <div class="two" style="margin-top: 20px">
              {#each Object.entries(EEO_FIELDS) as [key, options] (key)}
                <label class="field">{EEO_LABELS[key as keyof typeof EEO_FIELDS]}
                  <select class="input select" name={key} bind:value={eeo[key]}>
                    {#each options as o (o.value)}<option value={o.value}>{o.label}</option>{/each}
                  </select>
                </label>
              {/each}
            </div>
            <div style="display: flex; justify-content: flex-end; gap: 8px; margin-top: 24px; padding-top: 20px; border-top: 1px solid #1d2026">
              <button
                class="btn"
                type="button"
                disabled={data.loadError}
                onclick={() => {
                  for (const k of Object.keys(eeo)) eeo[k] = 'prefer_not';
                  saveFields('eeo-clear', 'clearEeo', {});
                }}
              >{saving === 'eeo-clear' ? 'Clearing…' : saved === 'eeo-clear' ? 'Cleared' : 'Clear all'}</button>
              {@render saveButton('eeo', 'Save answers')}
            </div>
          </form>
        {:else if section === 'matching'}
          <h2>Daily matching</h2>
          <p class="panel-lead">JobScanr finds roles and lines them up. You always apply on the employer’s site.</p>
          <form onsubmit={submitForm('matching', 'saveAutoApply')}>
            <fieldset style="margin: 24px 0 0; padding: 0; border: 0; display: flex; flex-direction: column; gap: 12px">
              <legend class="sr-only">Mode</legend>
              {#each [{ v: 'approval_required', l: 'On', h: 'New matches land in your Inbox each morning and in your email digest.' }, { v: 'disabled', l: 'Paused', h: 'No new matches and no digest until you switch back. Nothing is deleted.' }] as o (o.v)}
                <label style="display: flex; gap: 14px; align-items: flex-start; padding: 18px; border-radius: 16px; border: 1px solid {mode === o.v ? (o.v === 'disabled' ? '#ff7a7a' : '#ffffff') : '#2a2e37'}; background: #15171c; cursor: pointer">
                  <input type="radio" name="autoApplyMode" value={o.v} bind:group={mode} style="margin-top: 4px; accent-color: #ffffff" />
                  <span><span class="lbl">{o.l}</span><span class="help" style="display: block; margin-top: 4px">{o.h}</span></span>
                </label>
              {/each}
            </fieldset>
            <div style="display: flex; justify-content: flex-end; margin-top: 24px">{@render saveButton('matching', 'Save', true)}</div>
          </form>
        {:else if section === 'answers'}
          <h2>Saved answers</h2>
          <p class="panel-lead">
            Questions only you can answer, collected from the forms Fill it for me opens. Answer once; Fill it for me types the
            answer into every form that asks the same thing, and you check it before submitting. Answers stay in JobScanr.
          </p>
          <div style="margin-top: 20px; display: flex; flex-direction: column">
            {#each data.answers ?? [] as a (a.id)}
              <form class="block" onsubmit={submitForm(`a${a.id}`, 'saveAnswer')}>
                <input type="hidden" name="id" value={a.id} />
                <label class="lbl" for="q{a.id}">
                  {a.question}
                  {#if !a.answer?.trim()}<span style="margin-left: 8px; font-size: 13px; color: #f5b84a">Needs an answer</span>{/if}
                </label>
                <textarea id="q{a.id}" name="answer" class="input" rows="2" maxlength="1000" style="min-height: 72px">{a.answer ?? ''}</textarea>
                <div style="display: flex; justify-content: flex-end; gap: 8px">
                  <button class="btn sm" type="button" onclick={() => saveFields(`d${a.id}`, 'deleteAnswer', { id: String(a.id) })}>Clear</button>
                  {@render saveButton(`a${a.id}`, 'Save', true)}
                </div>
              </form>
            {:else}
              <p class="help">No questions yet. They appear here when a form asks something only you can answer.</p>
            {/each}
          </div>
        {:else if section === 'drafts'}
          <h2>Drafted answers</h2>
          <p class="panel-lead">For Fill it for me on Greenhouse, Lever and Ashby forms. You read, edit and submit every answer yourself.</p>
          <form onsubmit={submitForm('drafts', 'saveDrafts')}>
            <input type="hidden" name="llmDrafts" value={String(drafts)} />
            <label class="switch-row" style="margin-top: 24px">
              <span>
                <span class="lbl">Draft answers to open questions from my CV</span>
                <span class="help" style="display: block; margin-top: 6px">
                  Questions like “Why do you want to join?” get a short draft typed into the form. To write it, your CV text, the job
                  description and any note you add to a draft go to Groq, an AI provider. Drafts can be wrong, so check every one.
                  Turning this off stops drafts at once.
                </span>
              </span>
              <input class="switch" type="checkbox" role="switch" bind:checked={drafts} />
            </label>
            <div style="display: flex; justify-content: flex-end; margin-top: 24px">{@render saveButton('drafts', 'Save', true)}</div>
          </form>
        {:else}
          <h2>Account</h2>
          <div style="margin-top: 24px; display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; padding: 20px; border-radius: 16px; background: #15171c; border: 1px solid #2a2e37">
            <div>
              <div class="lbl">{data.demo ? 'Demo mode' : 'Signed in with Google'}</div>
              <div class="help">{data.profile?.email ?? ''}</div>
            </div>
            <form method="POST" action="/login?/logout"><button class="btn" type="submit">Sign out</button></form>
          </div>
        {/if}
      </div>
    {/key}
    {#if msg}
      <p class={msg.error ? 'formmsg' : 'sr-only'} role={msg.error ? 'alert' : 'status'} style="margin-top: 12px">{msg.text}</p>
    {/if}
  </div>
</main>
