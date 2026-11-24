<script lang="ts">
  import type { Snippet } from 'svelte';
  import Icon from '$lib/components/Icon.svelte';
  import RemoteFill from '$lib/components/RemoteFill.svelte';
  import type { ApplicationRecord } from '$lib/types';

  interface Profile {
    full_name: string;
    email: string;
    phone: string;
    location: string;
    linkedin: string;
    github: string;
    portfolio: string;
    resume_filename: string;
  }

  interface Props {
    application: ApplicationRecord | null;
    profile: Profile | null;
    onclose: () => void;
    /** Mark as Applied / Not Interested forms, rendered by the page so they share its submit handling. */
    actions: Snippet<[ApplicationRecord]>;
    /** The user is in the "Fill it for me" trial (#129). */
    remoteApply?: boolean;
  }

  let { application, profile, onclose, actions, remoteApply = false }: Props = $props();

  const canFill = $derived(
    remoteApply && application?.status === 'manual_apply' && ['greenhouse', 'lever', 'ashby'].includes(application.ats_platform)
  );

  // Keyed to the application, so another application never shows a stale message.
  let copied = $state<{ id: number; text: string } | null>(null);

  const fields = $derived(
    (
      [
        ['Name', profile?.full_name],
        ['Email', profile?.email],
        ['Phone', profile?.phone],
        ['Location', profile?.location],
        ['LinkedIn', profile?.linkedin],
        ['GitHub', profile?.github],
        ['Portfolio', profile?.portfolio]
      ] as [string, string | undefined][]
    ).filter((field): field is [string, string] => Boolean(field[1]))
  );

  const day = (iso: string | null) =>
    iso ? new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }) : '';

  /** Moves focus into the drawer when it opens and back to where it was when it closes. */
  function focusOnOpen(node: HTMLElement) {
    const previous = document.activeElement as HTMLElement | null;
    node.querySelector<HTMLElement>('a[href], button')?.focus();
    return () => previous?.focus?.();
  }

  async function copy(id: number, label: string, value: string) {
    try {
      await navigator.clipboard.writeText(value);
      copied = { id, text: `${label} copied.` };
    } catch {
      // The value stays visible and selectable.
      copied = { id, text: `Could not copy ${label}. Select the text and copy it instead.` };
    }
  }

  function handleKeydown(e: KeyboardEvent & { currentTarget: HTMLElement }) {
    if (e.key === 'Escape') {
      onclose();
      return;
    }
    if (e.key !== 'Tab') return;
    const focusable = e.currentTarget.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input, select, textarea');
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }
</script>

{#if application}
  <!-- Clicking the backdrop closes it; Escape does the same from the keyboard. -->
  <div
    class="fixed inset-0 z-50 flex justify-end bg-slate-900/40"
    onclick={(e) => e.target === e.currentTarget && onclose()}
    role="presentation"
  >
    <div
      {@attach focusOnOpen}
      onkeydown={handleKeydown}
      class="flex h-full w-full max-w-[560px] flex-col overflow-y-auto bg-card shadow-2xl has-[iframe]:max-w-[1100px]"
      role="dialog"
      tabindex="-1"
      aria-modal="true"
      aria-labelledby="applyTitle"
    >
      <div class="flex items-start justify-between gap-3 border-b border-border-main p-6 sm:p-7">
        <div class="min-w-0">
          <span class="tag-platform">
            via {application.ats_platform.charAt(0).toUpperCase() + application.ats_platform.slice(1)}
          </span>
          <h2 id="applyTitle" class="mt-2 break-words text-lg font-bold text-content-primary">{application.title}</h2>
          <div class="text-xs text-content-caption">
            {application.company_name}{application.location ? ` · ${application.location}` : ''}
          </div>
        </div>
        <button type="button" class="btn-secondary !p-1.5" onclick={onclose} aria-label="Close">
          <Icon name="close" size={14} />
        </button>
      </div>

      <div class="flex flex-1 flex-col gap-6 p-6 sm:p-7">
        {#if canFill}
          {#key application.id}
            <!-- The live view shows a desktop-sized page, so the drawer widens while it is open (has-[iframe]). -->
            <RemoteFill applicationId={application.id} />
          {/key}
        {/if}
        <section class="space-y-2">
          <h3 class="text-xs font-semibold text-content-primary">1. Open the posting</h3>
          {#if application.url !== '#'}
            <a href={application.url} target="_blank" rel="noopener noreferrer" class="btn-action !text-xs">
              Apply on the employer's site
              <Icon name="external-link" size={12} />
            </a>
          {:else}
            <p class="text-xs text-content-muted">
              This posting's link is not a normal web address, so it is not shown. Search for the role on the company's
              careers page.
            </p>
          {/if}
          {#if application.status === 'stale_closed'}
            <p class="text-xs text-content-muted">
              Our scanner last saw this posting on {day(application.last_seen_at)}. It may be closed.
            </p>
          {/if}
        </section>

        <section class="space-y-2">
          <h3 class="text-xs font-semibold text-content-primary">2. Copy your details</h3>
          {#if fields.length}
            <dl class="divide-y divide-border-subtle rounded-md border border-border-main">
              {#each fields as [label, value] (label)}
                <div class="flex items-center justify-between gap-3 px-3 py-2">
                  <div class="min-w-0">
                    <dt class="text-[11px] text-content-caption">{label}</dt>
                    <dd class="select-all break-words text-xs font-semibold text-content-primary">{value}</dd>
                  </div>
                  <button
                    type="button"
                    class="btn-secondary shrink-0 !py-1 !text-xs"
                    onclick={() => copy(application.id, label, value)}
                    aria-label="Copy {label}"
                  >
                    Copy
                  </button>
                </div>
              {/each}
            </dl>
          {:else}
            <p class="text-xs text-content-muted">No details saved yet. <a href="/settings" class="text-brand-blue underline">Add them in Settings</a>.</p>
          {/if}
          <p aria-live="polite" class="min-h-4 text-[11px] text-content-caption">
            {copied?.id === application.id ? copied.text : ''}
          </p>
        </section>

        <section class="space-y-2">
          <h3 class="text-xs font-semibold text-content-primary">3. Attach your CV</h3>
          {#if profile?.resume_filename}
            <!-- No use:enhance: the Settings action redirects to a 60-second download link. -->
            <form method="POST" action="/settings?/downloadCv">
              <button type="submit" class="btn-secondary !text-xs">
                <Icon name="download" size={13} />
                Download {profile.resume_filename}
              </button>
            </form>
          {:else}
            <p class="text-xs text-content-muted">
              No CV stored. <a href="/settings" class="text-brand-blue underline">Upload one in Settings</a>.
            </p>
          {/if}
        </section>
      </div>

      <div class="flex flex-wrap items-center justify-end gap-3 border-t border-border-main bg-subtle p-5 sm:px-7">
        {@render actions(application)}
      </div>
    </div>
  </div>
{/if}
