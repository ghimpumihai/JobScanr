<script lang="ts">
  import Icon from '$lib/components/Icon.svelte';
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

  let selectedLevels = $state<string[]>([
    'Graduate / New Grad',
    'Entry Level (0-1 yrs)',
    'Junior (1-2 yrs)'
  ]);

  let locations = $state<string[]>([
    'London',
    'Berlin',
    'Amsterdam',
    'Dublin',
    'Paris',
    'Remote EU'
  ]);

  let excludedKeywords = $state<string[]>([
    'Senior',
    'Lead',
    'Principal',
    'Staff',
    'Clearance',
    'C++'
  ]);

  let targetKeywords = $state<string[]>([
    'Backend',
    'Python',
    'Go',
    'Distributed Systems',
    'Platform'
  ]);

  let newLocation = $state('');
  let newTargetKeyword = $state('');
  let newKeyword = $state('');
  let toastMessage = $state<string | null>(null);

  function showToast(msg: string) {
    toastMessage = msg;
    setTimeout(() => {
      toastMessage = null;
    }, 3500);
  }

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

  function handleSave() {
    showToast("Preferences saved. Active for tomorrow's 06:00 UTC scan.");
  }
</script>

<svelte:head>
  <title>Profile &amp; Settings · JobScanr</title>
</svelte:head>

<div class="space-y-5">
  <!-- Card 1: CV & Candidate Identity -->
  <div class="card overflow-hidden">
    <div class="border-b border-border-subtle p-6">
      <h1 class="text-lg font-bold leading-snug text-content-primary">
        CV &amp; Candidate Identity
      </h1>
      <p class="mt-1 text-xs text-content-muted">
        Your uploaded resume is parsed and used strictly to ground screening answers.
      </p>
    </div>

    <div class="p-6">
      <!-- High-contrast CV Card -->
      <div class="mb-5 flex flex-col justify-between gap-4 rounded-md border border-border-main bg-subtle p-4 sm:flex-row sm:items-center">
        <div class="flex items-start gap-3">
          <Icon name="document" size={24} class="mt-0.5 shrink-0 text-brand-blue" />
          <div>
            <div class="font-semibold text-content-primary">
              {data.profile.resume_filename || 'stefan_ghimpu_cv_2026.pdf'}
            </div>
            <div class="text-xs text-content-caption">
              {data.profile.resume_size_kb || 142} KB · Uploaded {data.profile.resume_uploaded_at || 'Oct 12, 2026'} · Supabase Secure Storage
            </div>
            <div class="mt-1.5">
              <span class="status-badge bg-signal-emerald-bg text-signal-emerald-text">
                Ready for ATS Dispatch
              </span>
            </div>
          </div>
        </div>

        <div class="flex shrink-0 gap-2">
          <button
            type="button"
            class="btn-secondary !text-xs"
            onclick={() => showToast('Download started for resume file.')}
          >
            <Icon name="download" size={13} />
            Download CV
          </button>
          <button
            type="button"
            class="btn-secondary !text-xs"
            onclick={() => showToast('Upload dialog opened: PDF or DOCX max 2MB.')}
          >
            Replace CV
          </button>
        </div>
      </div>

      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <label for="fullName" class="mb-1 block text-xs font-semibold text-content-primary">
            Full Name
          </label>
          <input
            id="fullName"
            type="text"
            value={data.profile.full_name || 'Stefan Ghimpu'}
            class="w-full rounded-md border border-border-strong bg-card px-3 py-2 text-xs text-content-primary outline-none transition-colors focus:border-brand-blue"
          />
        </div>
        <div>
          <label for="contactEmail" class="mb-1 block text-xs font-semibold text-content-primary">
            Contact Email
          </label>
          <input
            id="contactEmail"
            type="email"
            value={data.profile.email || 'stefan@example.com'}
            class="w-full rounded-md border border-border-strong bg-card px-3 py-2 text-xs text-content-primary outline-none transition-colors focus:border-brand-blue"
          />
        </div>
      </div>
    </div>
  </div>

  <!-- Card 2: Job Search & Matching Filters -->
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

      <!-- Work Authorization -->
      <div>
        <label for="workAuthorization" class="mb-1 block text-xs font-semibold text-content-primary">
          Work Authorization Default
        </label>
        <input
          id="workAuthorization"
          type="text"
          value={data.profile.work_authorization}
          class="w-full rounded-md border border-border-strong bg-card px-3 py-2 text-xs text-content-primary outline-none transition-colors focus:border-brand-blue"
        />
        <p class="mt-1 text-[11px] text-content-caption">
          Pre-filled in ATS screening questions to prevent application drops.
        </p>
      </div>

      <div class="flex justify-end pt-3">
        <button type="button" class="btn-action" onclick={handleSave}>
          Save Preferences
          <Icon name="arrow-right" size={12} />
        </button>
      </div>
    </div>
  </div>

  <!-- Card 3: Account & Session -->
  <div class="card overflow-hidden">
    <div class="flex flex-col gap-4 p-6 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <h2 class="text-sm font-semibold text-content-primary">Account Session</h2>
        <p class="mt-0.5 text-xs text-content-muted">
          Signed in as <strong class="text-content-primary">{data.profile.email || 'stefan@example.com'}</strong>
        </p>
      </div>
      <a
        href="/login?logout=true"
        class="btn-secondary !text-xs"
        title="Sign out of JobScanr"
      >
        Sign Out of Account
      </a>
    </div>
  </div>
</div>

<!-- Toast Notice -->
{#if toastMessage}
  <div class="fixed bottom-6 right-6 z-50 rounded-md bg-content-primary px-5 py-3 text-xs font-medium text-card shadow-lg transition-all">
    {toastMessage}
  </div>
{/if}
