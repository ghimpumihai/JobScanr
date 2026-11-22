<script lang="ts">
  import { enhance } from '$app/forms';
  import type { SubmitFunction } from '@sveltejs/kit';
  import type { HTMLInputAttributes } from 'svelte/elements';
  import Icon from '$lib/components/Icon.svelte';
  import type { AutoApplyMode } from '$lib/types';
  import type { ActionData, PageData } from './$types';

  let { data, form }: { data: PageData; form: ActionData } = $props();

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

  const AUTO_APPLY_MODES: { value: AutoApplyMode; label: string; help: string }[] = [
    {
      value: 'approval_required',
      label: 'Approval required',
      help: 'Matches and digests continue; nothing new is submitted automatically.'
    },
    {
      value: 'auto_submit',
      label: 'Automatic submission',
      help: 'Eligible Greenhouse and Lever applications are queued for submission. Needs a confirmed CV.'
    },
    { value: 'disabled', label: 'Paused', help: 'No matching, no digest, no applications.' }
  ];

  const INPUT_CLASS =
    'w-full rounded-md border border-border-strong bg-card px-3 py-2 text-xs text-content-primary outline-none transition-colors focus:border-brand-blue';

  // Saved values: follow every save and upload. The CV, confirmation and auto-apply cards read these.
  const saved = $derived(data.profile);
  const confirmed = $derived(Boolean(saved?.resume_filename && saved.resume_confirmed_at));
  let mode = $derived(data.profile?.auto_apply_mode ?? 'approval_required');
  let dailyCap = $derived(data.profile?.max_daily_applications ?? 10);

  const summary = $derived([
    ['CV', saved?.resume_filename],
    ['Name', saved?.full_name],
    ['Email', saved?.email],
    ['Phone', saved?.phone],
    ['Location', saved?.location],
    ['LinkedIn', saved?.linkedin],
    ['GitHub', saved?.github],
    ['Portfolio', saved?.portfolio],
    ['Authorized to work', { yes: 'Yes', no: 'No' }[saved?.work_authorization ?? '']],
    ['Needs sponsorship', { yes: 'Yes', no: 'No' }[saved?.requires_sponsorship ?? '']],
    ['Years of experience', saved?.years_experience?.toString()],
    ['Notice period (days)', saved?.notice_period_days?.toString()]
  ]);

  // Form fields: seeded once, so saving never overwrites them with demo values and an upload keeps unsaved edits.
  // svelte-ignore state_referenced_locally
  const profile = data.profile;
  let selectedLevels = $state<string[]>([...(profile?.seniority_levels ?? [])]);
  let locations = $state<string[]>([...(profile?.preferred_locations ?? [])]);
  let excludedKeywords = $state<string[]>([...(profile?.excluded_keywords ?? [])]);
  let targetKeywords = $state<string[]>([...(profile?.target_keywords ?? [])]);

  let newLocation = $state('');
  let newTargetKeyword = $state('');
  let newKeyword = $state('');
  let pending = $state(false);
  // svelte-ignore state_referenced_locally -- downloadCv posts without JavaScript, so its result arrives on load
  let notice = $state(form ? { text: form.error ?? form.message ?? '', error: Boolean(form.error) } : null);
  let noticeTimer: ReturnType<typeof setTimeout>;

  function showNotice(text: string, error: boolean) {
    clearTimeout(noticeTimer);
    notice = { text, error };
    // Errors stay until dismissed.
    if (!error) noticeTimer = setTimeout(() => (notice = null), 6000);
  }

  const submit: SubmitFunction = ({ formElement }) => {
    pending = true;
    return async ({ result, update }) => {
      pending = false;
      if (result.type === 'success') {
        showNotice((result.data?.message as string) ?? 'Saved.', false);
      } else if (result.type === 'failure') {
        showNotice((result.data?.error as string) ?? 'Could not save.', true);
      } else if (result.type === 'error') {
        // Not update(): it would replace the page with an error page and lose unsaved edits.
        showNotice('The request failed. Check your connection and try again.', true);
        return;
      }
      await update({ reset: result.type === 'success' && formElement.id === 'cvForm' });
    };
  };

  function toggleSeniority(level: string) {
    if (selectedLevels.includes(level)) {
      selectedLevels = selectedLevels.filter((l) => l !== level);
    } else {
      selectedLevels = [...selectedLevels, level];
    }
  }

  function removeLocation(loc: string) {
    locations = locations.filter((l) => l !== loc);
  }

  function addLocation() {
    const trimmed = newLocation.trim();
    if (trimmed && !locations.includes(trimmed)) {
      locations = [...locations, trimmed];
      newLocation = '';
    }
  }

  function removeTargetKeyword(kw: string) {
    targetKeywords = targetKeywords.filter((k) => k !== kw);
  }

  function addTargetKeyword() {
    const trimmed = newTargetKeyword.trim();
    if (trimmed && !targetKeywords.includes(trimmed)) {
      targetKeywords = [...targetKeywords, trimmed];
      newTargetKeyword = '';
    }
  }

  function removeKeyword(kw: string) {
    excludedKeywords = excludedKeywords.filter((k) => k !== kw);
  }

  function addKeyword() {
    const trimmed = newKeyword.trim();
    if (trimmed && !excludedKeywords.includes(trimmed)) {
      excludedKeywords = [...excludedKeywords, trimmed];
      newKeyword = '';
    }
  }
</script>

<svelte:head>
  <title>Profile &amp; Settings · JobScanr</title>
</svelte:head>

<div class="space-y-5">
  {#if data.loadError}
    <div class="card border-l-4 border-red-500 p-4 text-xs text-content-primary" role="alert">
      Could not load your settings. Saving is disabled so nothing gets overwritten. Please reload.
    </div>
  {/if}

  <!-- Card 1: CV -->
  <div class="card overflow-hidden">
    <div class="border-b border-border-subtle p-6">
      <h1 class="text-lg font-bold leading-snug text-content-primary">CV</h1>
      <p class="mt-1 text-xs text-content-muted">
        Your original file is sent with applications exactly as you uploaded it.
      </p>
    </div>
    <div class="space-y-4 p-6">
      <div class="flex flex-col justify-between gap-4 rounded-md border border-border-main bg-subtle p-4 sm:flex-row sm:items-center">
        <div class="flex min-w-0 items-start gap-3">
          <Icon name="document" size={24} class="mt-0.5 shrink-0 text-brand-blue" />
          <div class="min-w-0">
            <div class="break-words font-semibold text-content-primary">
              {saved?.resume_filename ?? 'No CV uploaded'}
            </div>
            {#if saved?.resume_uploaded_at}
              <div class="text-xs text-content-caption">Uploaded {saved.resume_uploaded_at}</div>
            {/if}
            {#if saved?.resume_filename}
              <div class="mt-1.5">
                {#if confirmed}
                  <span class="status-badge bg-signal-emerald-bg text-signal-emerald-text">Confirmed</span>
                {:else}
                  <span class="status-badge bg-signal-amber-bg text-signal-amber-text">Needs confirmation</span>
                {/if}
              </div>
            {/if}
          </div>
        </div>
        {#if saved?.resume_filename}
          <!-- No use:enhance: the action redirects to a download on the storage origin. -->
          <form method="POST" action="?/downloadCv" class="shrink-0">
            <button type="submit" class="btn-secondary !text-xs">
              <Icon name="download" size={13} />
              Download CV
            </button>
          </form>
        {/if}
      </div>

      <form id="cvForm" method="POST" action="?/uploadCv" enctype="multipart/form-data" use:enhance={submit}>
        <label for="cv" class="mb-1 block text-xs font-semibold text-content-primary">
          {saved?.resume_filename ? 'Replace CV' : 'Upload CV'}
          <span class="font-normal text-content-caption">(PDF, DOCX or DOC, up to 2 MB)</span>
        </label>
        <div class="flex flex-col gap-2 sm:flex-row sm:items-center">
          <input
            id="cv"
            name="cv"
            type="file"
            accept=".pdf,.docx,.doc"
            required
            aria-describedby="cvHelp"
            class="w-full rounded-md border border-dashed border-border-strong bg-card px-3 py-4 text-xs text-content-primary"
          />
          <button type="submit" class="btn-secondary !text-xs disabled:opacity-60" disabled={!saved || pending}>
            Upload
          </button>
        </div>
        <p id="cvHelp" class="mt-1 text-[11px] text-content-caption">
          Choose a file or drop it on the field. A new CV must be confirmed again, and automatic submission stays off until
          then.
        </p>
      </form>
    </div>
  </div>

  <form method="POST" action="?/savePreferences" use:enhance={submit} class="space-y-5">
    <input type="hidden" name="seniorityLevels" value={JSON.stringify(selectedLevels)} />
    <input type="hidden" name="locations" value={JSON.stringify(locations)} />
    <input type="hidden" name="targetKeywords" value={JSON.stringify(targetKeywords)} />
    <input type="hidden" name="excludedKeywords" value={JSON.stringify(excludedKeywords)} />

    <!-- Card 2: Candidate details & screening answers -->
    <div class="card overflow-hidden">
      <div class="border-b border-border-subtle p-6">
        <h2 class="text-lg font-bold leading-snug text-content-primary">Candidate Details &amp; Screening Answers</h2>
        <p class="mt-1 text-xs text-content-muted">Sent to employers when an application asks for them.</p>
      </div>
      <div class="grid grid-cols-1 gap-4 p-6 sm:grid-cols-2">
        {@render field('fullName', 'First and last name', profile?.full_name, { autocomplete: 'name', maxlength: 120 })}
        <div>
          <label for="contactEmail" class="mb-1 block text-xs font-semibold text-content-primary">Contact Email</label>
          <input
            id="contactEmail"
            type="email"
            readonly
            value={profile?.email ?? ''}
            class="w-full rounded-md border border-border-main bg-subtle px-3 py-2 text-xs text-content-muted outline-none"
          />
        </div>
        {@render field('phone', 'Phone', profile?.phone, { type: 'tel', autocomplete: 'tel', maxlength: 120 })}
        {@render field('location', 'Current location', profile?.location, { maxlength: 120 })}
        {@render field('linkedin', 'LinkedIn', profile?.linkedin, { type: 'url', maxlength: 300 })}
        {@render field('github', 'GitHub', profile?.github, { type: 'url', maxlength: 300 })}
        {@render field('portfolio', 'Portfolio', profile?.portfolio, { type: 'url', maxlength: 300 })}
        {@render field('yearsExperience', 'Years of experience', profile?.years_experience, {
          type: 'number',
          min: 0,
          max: 50
        })}
        {@render field('noticePeriodDays', 'Notice period (days)', profile?.notice_period_days, {
          type: 'number',
          min: 0,
          max: 365
        })}
        <div>
          <label for="workAuthorization" class="mb-1 block text-xs font-semibold text-content-primary">
            Authorized to work in your target countries?
          </label>
          <select id="workAuthorization" name="workAuth" value={profile?.work_authorization ?? ''} class={INPUT_CLASS}>
            <option value="" disabled>Select…</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
        </div>
        <div>
          <label for="requiresSponsorship" class="mb-1 block text-xs font-semibold text-content-primary">
            Need visa sponsorship, now or in the future?
          </label>
          <select
            id="requiresSponsorship"
            name="requiresSponsorship"
            value={profile?.requires_sponsorship ?? ''}
            class={INPUT_CLASS}
          >
            <option value="" disabled>Select…</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
        </div>
      </div>
    </div>

  <!-- Card 3: Job Search & Matching Filters -->
  <div class="card overflow-hidden">
    <div class="border-b border-border-subtle p-6">
      <h2 class="text-lg font-bold leading-snug text-content-primary">
        Job Search &amp; Matching Filters
      </h2>
      <p class="mt-1 text-xs text-content-muted">
        Controls daily scraping and pre-filtering across 388 company feeds.
      </p>
    </div>

    <div class="space-y-5 p-6">
      <!-- Comprehensive Seniority Levels -->
      <fieldset>
        <legend class="mb-2 block text-xs font-semibold text-content-primary">
          Target Seniority Levels <span class="font-normal text-content-caption">(Select all applicable)</span>
        </legend>
        <div class="flex flex-wrap gap-2">
          {#each ALL_SENIORITY_LEVELS as level}
            {@const active = selectedLevels.includes(level)}
            <button
              type="button"
              class="inline-flex min-h-[36px] sm:min-h-0 items-center gap-1.5 rounded-md border px-3 py-2 sm:py-1.5 text-xs font-semibold transition-all {active
                ? 'border-brand-blue bg-brand-blue text-white shadow-sm'
                : 'border-border-strong bg-card text-content-secondary hover:bg-hover'}"
              onclick={() => toggleSeniority(level)}
              aria-pressed={active}
            >
              {level}
            </button>
          {/each}
        </div>
      </fieldset>

      <!-- Preferred Locations -->
      <div>
        <label for="addLocationInput" class="mb-1 block text-xs font-semibold text-content-primary">
          Preferred Locations
        </label>
        <div class="mb-2 flex flex-wrap gap-2">
          {#each locations as loc}
            <span class="inline-flex items-center gap-1.5 rounded-md border border-border-strong bg-card px-2.5 py-1 text-xs font-semibold text-content-secondary">
              {loc}
              <button
                type="button"
                class="inline-flex min-h-[28px] min-w-[28px] items-center justify-center rounded text-content-caption transition-colors hover:bg-red-500/10 hover:text-red-500"
                onclick={() => removeLocation(loc)}
                aria-label="Remove {loc}"
              >
                <Icon name="close" size={10} />
              </button>
            </span>
          {/each}
        </div>
        <div class="flex max-w-sm gap-2">
          <input
            id="addLocationInput"
            type="text"
            placeholder="Add location (e.g. Zurich, Munich)..."
            aria-label="Add preferred European work location"
            bind:value={newLocation}
            onkeydown={(e) => e.key === 'Enter' && (e.preventDefault(), addLocation())}
            class="flex-1 rounded-md border border-border-strong bg-card px-3 py-1.5 text-xs text-content-primary outline-none focus:border-brand-blue"
          />
          <button type="button" class="btn-secondary !py-1 !text-xs" onclick={addLocation} aria-label="Add location">
            Add
          </button>
        </div>
      </div>

      <!-- Target Keywords (Positive Match Filter) -->
      <div>
        <label for="addTargetKeywordInput" class="mb-1 block text-xs font-semibold text-content-primary">
          Target Title Keywords <span class="font-normal text-content-caption">(Positive Match Filter)</span>
        </label>
        <div class="mb-2 flex flex-wrap gap-2">
          {#each targetKeywords as kw}
            <span class="inline-flex items-center gap-1.5 rounded-md border border-border-strong bg-card px-2.5 py-1 text-xs font-semibold text-content-secondary">
              {kw}
              <button
                type="button"
                class="inline-flex min-h-[28px] min-w-[28px] items-center justify-center rounded text-content-caption transition-colors hover:bg-red-500/10 hover:text-red-500"
                onclick={() => removeTargetKeyword(kw)}
                aria-label="Remove target keyword {kw}"
              >
                <Icon name="close" size={10} />
              </button>
            </span>
          {/each}
        </div>
        <div class="flex max-w-sm gap-2">
          <input
            id="addTargetKeywordInput"
            type="text"
            placeholder="Add target keyword (e.g. Backend, Python, Go)..."
            aria-label="Add positive title keyword to target"
            bind:value={newTargetKeyword}
            onkeydown={(e) => e.key === 'Enter' && (e.preventDefault(), addTargetKeyword())}
            class="flex-1 rounded-md border border-border-strong bg-card px-3 py-1.5 text-xs text-content-primary outline-none focus:border-brand-blue"
          />
          <button type="button" class="btn-secondary !py-1 !text-xs" onclick={addTargetKeyword} aria-label="Add target keyword">
            Add
          </button>
        </div>
        <p class="mt-1 text-[11px] text-content-caption">
          Positions matching these keywords will be prioritized in your daily radar.
        </p>
      </div>

      <!-- Excluded Keywords -->
      <div>
        <label for="addKeywordInput" class="mb-1 block text-xs font-semibold text-content-primary">
          Excluded Title Keywords <span class="font-normal text-content-caption">(Negative Filter)</span>
        </label>
        <div class="mb-2 flex flex-wrap gap-2">
          {#each excludedKeywords as kw}
            <span class="inline-flex items-center gap-1.5 rounded-md border border-border-strong bg-card px-2.5 py-1 text-xs font-semibold text-content-secondary">
              {kw}
              <button
                type="button"
                class="inline-flex min-h-[28px] min-w-[28px] items-center justify-center rounded text-content-caption transition-colors hover:bg-red-500/10 hover:text-red-500"
                onclick={() => removeKeyword(kw)}
                aria-label="Remove {kw}"
              >
                <Icon name="close" size={10} />
              </button>
            </span>
          {/each}
        </div>
        <div class="flex max-w-sm gap-2">
          <input
            id="addKeywordInput"
            type="text"
            placeholder="Add negative keyword (e.g. Rust, Manager)..."
            aria-label="Add negative title keyword to exclude"
            bind:value={newKeyword}
            onkeydown={(e) => e.key === 'Enter' && (e.preventDefault(), addKeyword())}
            class="flex-1 rounded-md border border-border-strong bg-card px-3 py-1.5 text-xs text-content-primary outline-none focus:border-brand-blue"
          />
          <button type="button" class="btn-secondary !py-1 !text-xs" onclick={addKeyword} aria-label="Add excluded keyword">
            Add
          </button>
        </div>
      </div>

      <div class="flex justify-end pt-3">
        <button type="submit" class="btn-action disabled:opacity-60" disabled={!saved || pending}>
          Save Preferences
          <Icon name="arrow-right" size={12} />
        </button>
      </div>
    </div>
  </div>
</form>

  <!-- Card 4: Review & Confirm -->
  <div class="card overflow-hidden">
    <div class="border-b border-border-subtle p-6">
      <h2 class="text-lg font-bold leading-snug text-content-primary">Review &amp; Confirm</h2>
      <p class="mt-1 text-xs text-content-muted">
        These are your saved values. Edits above count only after you save them.
      </p>
    </div>
    <div class="space-y-4 p-6">
      <dl class="grid grid-cols-1 gap-x-4 gap-y-2 text-xs sm:grid-cols-2">
        {#each summary as [label, value]}
          <div class="min-w-0">
            <dt class="text-content-caption">{label}</dt>
            <dd class="break-words font-semibold text-content-primary">{value || 'Not set'}</dd>
          </div>
        {/each}
      </dl>
      <form method="POST" action="?/confirmCv" use:enhance={submit} class="flex flex-wrap items-center justify-end gap-3">
        <input type="hidden" name="resumeUploadedAt" value={saved?.resume_uploaded_at_raw ?? ''} />
        {#if confirmed}
          <span class="status-badge bg-signal-emerald-bg text-signal-emerald-text">Confirmed</span>
        {/if}
        <button
          type="submit"
          class="btn-action disabled:opacity-60"
          disabled={!saved?.resume_filename || confirmed || pending}
        >
          <Icon name="check" size={12} />
          Confirm CV and details
        </button>
      </form>
    </div>
  </div>

  <!-- Card 5: Auto-Apply -->
  <div class="card overflow-hidden">
    <div class="border-b border-border-subtle p-6">
      <h2 class="text-lg font-bold leading-snug text-content-primary">Auto-Apply</h2>
      <p class="mt-1 text-xs text-content-muted">
        Applications already queued are still sent unless you choose Paused.
      </p>
    </div>
    <form method="POST" action="?/saveAutoApply" use:enhance={submit} class="space-y-5 p-6">
      <fieldset class="space-y-3">
        <legend class="mb-2 text-xs font-semibold text-content-primary">Mode</legend>
        {#each AUTO_APPLY_MODES as option}
          <div class="flex items-start gap-2">
            <input
              id="mode-{option.value}"
              type="radio"
              name="autoApplyMode"
              value={option.value}
              bind:group={mode}
              disabled={option.value === 'auto_submit' && !confirmed}
              aria-describedby="mode-{option.value}-help"
              class="mt-0.5"
            />
            <div class="text-xs">
              <label for="mode-{option.value}" class="font-semibold text-content-primary">{option.label}</label>
              <p id="mode-{option.value}-help" class="text-content-muted">
                {option.help}
                {#if option.value === 'auto_submit' && !confirmed}Confirm your CV above to enable this.{/if}
              </p>
            </div>
          </div>
        {/each}
      </fieldset>
      <div>
        <label for="maxDailyApplications" class="mb-1 block text-xs font-semibold text-content-primary">
          Daily application limit: <output for="maxDailyApplications">{dailyCap}</output>
        </label>
        <input
          id="maxDailyApplications"
          name="maxDailyApplications"
          type="range"
          min="5"
          max="25"
          step="1"
          bind:value={dailyCap}
          class="w-full max-w-sm"
        />
      </div>
      <div class="flex justify-end">
        <button type="submit" class="btn-action disabled:opacity-60" disabled={!saved || pending}>
          Save Auto-Apply
          <Icon name="arrow-right" size={12} />
        </button>
      </div>
    </form>
  </div>

  <!-- Card 6: Account & Session -->
  <div class="card overflow-hidden">
    <div class="flex flex-col gap-4 p-6 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <h2 class="text-sm font-semibold text-content-primary">Account Session</h2>
        <p class="mt-0.5 text-xs text-content-muted">
          Signed in as <strong class="text-content-primary">{profile?.email ?? ''}</strong>
        </p>
      </div>
      <a
        href="/login?logout=true"
        class="btn-secondary !text-xs"
        title="Sign out of JobScanr"
      >
        Sign Out
      </a>
    </div>
  </div>
</div>

<!-- The region stays in the page so screen readers announce each new message. -->
<div aria-live="polite" class="fixed bottom-6 right-6 z-50 max-w-[calc(100vw-3rem)]">
  {#if notice}
    <div class="flex items-start gap-3 rounded-md bg-content-primary px-5 py-3 text-xs font-medium text-card shadow-lg">
      <span>{#if notice.error}<strong>Error:</strong>{' '}{/if}{notice.text}</span>
      <button type="button" onclick={() => (notice = null)} aria-label="Dismiss message">
        <Icon name="close" size={12} />
      </button>
    </div>
  {/if}
</div>

{#snippet field(id: string, label: string, value: string | number | undefined, attributes: HTMLInputAttributes)}
  <div>
    <label for={id} class="mb-1 block text-xs font-semibold text-content-primary">{label}</label>
    <input {id} name={id} type="text" value={value ?? ''} class={INPUT_CLASS} {...attributes} />
  </div>
{/snippet}
