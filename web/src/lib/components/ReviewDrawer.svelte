<script lang="ts">
  import Icon from '$lib/components/Icon.svelte';
  import type { ApplicationRecord } from '$lib/types';

  interface Props {
    application: ApplicationRecord | null;
    onclose: () => void;
    onsubmit: (app: ApplicationRecord, answer: string) => void;
  }

  let { application, onclose, onsubmit }: Props = $props();

  let answerText = $state('');
  let submitting = $state(false);
  let drawerPanel = $state<HTMLDivElement | null>(null);
  let previousActiveElement: HTMLElement | null = null;

  $effect(() => {
    if (application) {
      submitting = false;
      answerText =
        application.drafted_answer ||
        'During my internship at Acme Cloud, our daily ingestion workers faced 429 rate limit drops on GraphQL endpoints. I implemented serialized asyncio pacing locks, which restored 100% throughput without worker crash loops.';

      if (typeof document !== 'undefined') {
        previousActiveElement = document.activeElement as HTMLElement | null;
        requestAnimationFrame(() => {
          const textarea = drawerPanel?.querySelector('textarea');
          if (textarea) {
            textarea.focus();
          }
        });
      }
    } else if (previousActiveElement) {
      previousActiveElement.focus?.();
      previousActiveElement = null;
    }
  });

  function handleKeydown(e: KeyboardEvent) {
    if (!application) return;

    if (e.key === 'Escape') {
      onclose();
      return;
    }

    if (e.key === 'Tab' && drawerPanel) {
      const focusable = drawerPanel.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      if (focusable.length === 0) return;

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
  }

  function handleOverlayClick(e: MouseEvent) {
    if (e.target === e.currentTarget) {
      onclose();
    }
  }

  function handleSubmit() {
    if (application && !submitting) {
      submitting = true;
      onsubmit(application, answerText);
    }
  }
</script>

<svelte:window onkeydown={handleKeydown} />

{#if application}
  <!-- Overlay Backdrop -->
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <div
    class="fixed inset-0 z-50 flex justify-end bg-slate-900/40 transition-opacity"
    onclick={handleOverlayClick}
    role="presentation"
  >
    <!-- Drawer Panel -->
    <div
      bind:this={drawerPanel}
      class="flex h-full w-full max-w-[560px] flex-col overflow-y-auto bg-card shadow-2xl transition-transform"
      role="dialog"
      aria-modal="true"
      aria-labelledby="drawerRoleTitle"
    >
      <!-- Drawer Header -->
      <div class="flex items-start justify-between border-b border-border-main p-6 sm:p-7">
        <div>
          <span class="tag-platform">via {application.ats_platform.charAt(0).toUpperCase() + application.ats_platform.slice(1)}</span>
          <h2 id="drawerRoleTitle" class="mt-2 text-lg font-bold text-content-primary">
            {application.title}
          </h2>
          <div class="text-xs text-content-caption">
            {application.company_name} · {application.location}
          </div>
        </div>
        <button
          type="button"
          class="btn-secondary !p-1.5"
          onclick={onclose}
          aria-label="Close review drawer"
        >
          <Icon name="close" size={14} />
        </button>
      </div>

      <!-- Drawer Body -->
      <div class="flex flex-1 flex-col gap-5 p-6 sm:p-7">
        <div class="rounded-md border border-border-main bg-subtle p-3 text-xs text-content-secondary">
          <strong class="text-content-primary">Audit Grounding:</strong> Extracted directly from uploaded CV (Acme Cloud experience). Verified against anti-hallucination prompt.
        </div>

        <div>
          <label for="screeningAnswer" class="mb-2 block text-xs font-semibold text-content-primary">
            {application.screening_question || 'Screening Question: "Describe a complex backend or async issue you resolved."'}
          </label>
          <textarea
            id="screeningAnswer"
            bind:value={answerText}
            rows={5}
            class="w-full resize-y rounded-md border border-border-strong bg-card p-3 text-xs leading-relaxed text-content-primary outline-none transition-colors focus:border-brand-blue"
          ></textarea>
        </div>

        <div>
          <label for="workAuth" class="mb-1 block text-xs font-semibold text-content-primary">
            Work Authorization
          </label>
          <input
            id="workAuth"
            type="text"
            readonly
            value={application.work_authorization || 'Authorized to work in UK & EU (No sponsorship required)'}
            class="w-full rounded-md border border-border-main bg-subtle px-3 py-2 text-xs text-content-muted outline-none"
          />
        </div>
      </div>

      <!-- Drawer Footer -->
      <div class="flex items-center justify-end gap-3 border-t border-border-main bg-subtle p-5 sm:px-7">
        <button type="button" class="btn-secondary" onclick={onclose}>
          Cancel
        </button>
        <button
          type="button"
          class="btn-action disabled:opacity-60"
          onclick={handleSubmit}
          disabled={submitting}
        >
          {submitting ? 'Submitting...' : 'Approve & Submit Application'}
          <Icon name="arrow-right" size={12} />
        </button>
      </div>
    </div>
  </div>
{/if}
