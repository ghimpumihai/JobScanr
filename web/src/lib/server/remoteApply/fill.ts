// Fills an employer's application form from a fill plan and the user's profile (#129, spike).
// Never submits: the only clicks are on dropdown options (role=option), and each is checked not to be a submit
// control. Works on the page's main frame only, so captcha widgets (always in iframes) are never touched.
import type { Locator, Page } from 'playwright-core';

export interface PlanField {
  name: string;
  label: string;
  type: string;
  value: string | number | boolean;
  option_label?: string;
}

/** A question left for the user; open-ended ones may carry an LLM draft (#59). */
export interface ForUserField {
  name: string;
  label: string;
  reason: string;
  type?: string;
  draft?: string;
  draft_status?: 'generated' | 'unanswered';
  draft_reason?: string;
  /** Answer memory: the saved question this one is linked to by the pipeline, and how. */
  memory_id?: number;
  memory_match?: 'exact' | 'similar';
  /** The saved answer, set by session.ts at fill time; never stored in the plan. */
  memory_answer?: string;
}

export interface FillPlan {
  version: number;
  platform: string;
  posting_url: string | null;
  fields: PlanField[];
  for_user: ForUserField[];
}

export interface FillProfile {
  full_name?: string;
  email?: string;
  phone?: string;
  location?: string;
  linkedin?: string;
  github?: string;
  portfolio?: string;
}

export interface Cv {
  name: string;
  mimeType: string;
  buffer: Buffer;
}

export interface FillResult {
  planned: number;
  filled: number;
  /** Labels of fields we meant to fill but could not. */
  unfilled: string[];
  /** Labels of questions that got an LLM draft for the user to review (#59). */
  drafted: string[];
  /** Questions filled from the answer memory; similar ones are shown for checking. */
  remembered: { label: string; similar: boolean }[];
  cvAttached: boolean;
}

interface Control {
  index: number;
  tag: string;
  type: string;
  role: string;
  name: string;
  id: string;
  /** Label, placeholder, aria-label, autocomplete, name and id, lower-cased, for matching. */
  text: string;
  /** What a person reads as the field's question: its label (label elements and aria-labelledby), aria-label and
   * placeholder, each trimmed. Checked one by one, so a short label with a short placeholder still counts as short. */
  prompts: string[];
  visible: boolean;
}

/**
 * Profile values only go into standard contact fields, never into an employer's own questions: not textareas, not
 * Greenhouse question_* or Lever cards[...] fields, and elsewhere only short labels that are not questions
 * (Ashby names its own fields with UUIDs, its Phone and LinkedIn fields included).
 */
function standardField(c: Control): boolean {
  if (c.tag === 'textarea' || /^question_|^cards\[/.test(c.name)) return false;
  return c.prompts.every((p) => p.length <= 32 && !p.includes('?'));
}

const CONTROLS = 'input, textarea, select';

/** Key for matching saved questions; must match normalize_question in jobs/apply/llm_answers.py. */
export function normalizeQuestion(text: string): string {
  const cleaned = text.normalize('NFC').toLowerCase().replace(/[^\p{L}\p{N}]/gu, ' ');
  return Array.from(cleaned.split(/\s+/).filter(Boolean).join(' ')).slice(0, 500).join('').trimEnd();
}

function freeText(c: Control): boolean {
  return c.tag === 'textarea' || (c.tag === 'input' && c.role !== 'combobox' && !['checkbox', 'radio', 'file'].includes(c.type));
}

type StandardKey = 'first_name' | 'last_name' | 'full_name' | 'email' | 'phone' | 'location' | 'linkedin' | 'github' | 'portfolio';

// "First and Last Name" (Ashby) is one field for the whole name.
const BOTH_NAMES = /first\s*(and|&|\/)\s*last/;
// "Legal Name (if different than above)" and similar must stay empty.
// "Please share the full name of your major" (Datadog) is not the person's name either.
const OTHER_NAME =
  /company|org|user|preferred|middle|nick|school|reference|legal|different|maiden|former|emergency|name of|major|degree|university|college/;

// First match wins, and each control is used once, so the more specific rules come first. Word boundaries
// matter: "ethnicity" contains "city" (seen on a real Greenhouse form).
const STANDARD: [StandardKey, (c: Control) => boolean][] = [
  ['full_name', (c) => BOTH_NAMES.test(c.text) && !OTHER_NAME.test(c.text)],
  ['first_name', (c) => !BOTH_NAMES.test(c.text) && /first[\s_-]*name|given[\s_-]*name|given-name/.test(c.text)],
  ['last_name', (c) => !BOTH_NAMES.test(c.text) && /last[\s_-]*name|family[\s_-]*name|surname|family-name/.test(c.text)],
  ['email', (c) => c.type === 'email' || /e-?mail/.test(c.text)],
  ['phone', (c) => c.type === 'tel' || /phone|mobile/.test(c.text)],
  ['linkedin', (c) => /linkedin/.test(c.text)],
  ['github', (c) => /github/.test(c.text)],
  ['portfolio', (c) => /portfolio|personal (web)?site|\bwebsite\b/.test(c.text)],
  ['location', (c) => /\blocation\b|\bcity\b/.test(c.text)],
  ['full_name', (c) => /\bname\b/.test(c.text) && !/first|last/.test(c.text) && !OTHER_NAME.test(c.text)]
];

function standardValues(profile: FillProfile): Record<StandardKey, string | undefined> {
  const parts = (profile.full_name ?? '').trim().split(/\s+/).filter(Boolean);
  return {
    first_name: parts[0],
    last_name: parts.length > 1 ? parts.slice(1).join(' ') : undefined,
    full_name: profile.full_name?.trim() || undefined,
    email: profile.email,
    phone: profile.phone,
    location: profile.location,
    linkedin: profile.linkedin,
    github: profile.github,
    portfolio: profile.portfolio
  };
}

// Each control is tagged once and found again by its tag: dropdowns insert inputs while the form is being filled,
// which shifted positional (nth) lookups onto the wrong fields on a real Greenhouse form (Phone got the city).
const TAG = 'data-jobscanr-control';
const byTag = (page: Page, index: number) => page.locator(`[${TAG}="${index}"]`);

async function listControls(page: Page): Promise<Control[]> {
  return page.locator(CONTROLS).evaluateAll((els, tag) =>
    els.map((el, index) => {
      const e = el as HTMLInputElement;
      e.setAttribute(tag, String(index));
      const labels = Array.from(e.labels ?? []).map((l) => l.textContent ?? '');
      const labelledBy = (e.getAttribute('aria-labelledby') ?? '')
        .split(/\s+/)
        .map((id) => (id ? document.getElementById(id)?.textContent ?? '' : ''));
      const clean = (s: string | null) => (s ?? '').replace(/\s+/g, ' ').replace(/[*✱]/g, '').trim();
      const prompts = [clean([...labels, ...labelledBy].join(' ')), clean(e.getAttribute('aria-label')), clean(e.getAttribute('placeholder'))];
      const text = [
        ...labels,
        ...labelledBy,
        e.getAttribute('placeholder'),
        e.getAttribute('aria-label'),
        e.getAttribute('autocomplete'),
        e.name,
        e.id
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      const style = getComputedStyle(e);
      const rect = e.getBoundingClientRect();
      return {
        index,
        tag: e.tagName.toLowerCase(),
        type: (e.getAttribute('type') ?? '').toLowerCase(),
        role: (e.getAttribute('role') ?? '').toLowerCase(),
        name: e.name ?? '',
        id: e.id ?? '',
        text,
        prompts,
        // File inputs are usually hidden behind a styled button; they still accept files.
        visible: e.type === 'file' || (style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0)
      };
    }), TAG
  );
}

const STEP_MS = 2000; // every wait is bounded: Playwright's own default is 30 s, which made each dropdown take 33 s

/** Refuses to click anything that could submit the form. */
async function clickOption(option: Locator): Promise<void> {
  const unsafe = await option.evaluate(
    (el) => {
      const tag = el.tagName.toLowerCase();
      const type = (el.getAttribute('type') ?? '').toLowerCase();
      return tag === 'button' || type === 'submit' || type === 'image' || el.getAttribute('role') !== 'option';
    },
    undefined,
    { timeout: STEP_MS }
  );
  if (unsafe) throw new Error('refusing to click a control that is not a dropdown option');
  await option.click({ timeout: STEP_MS });
}

/** Opens the dropdown and picks the option whose text is exactly `label`; otherwise closes it and reports false. */
async function pickOption(page: Page, el: Locator, label: string): Promise<boolean> {
  try {
    await el.click({ timeout: STEP_MS }); // opens the list; a combobox input never submits
    // Search only the list this dropdown controls (react-select names it once open), and only ARIA options: native
    // <option>s of other <select>s also have the option role and would be found first.
    const listId = (await el.getAttribute('aria-controls', { timeout: STEP_MS })) ?? (await el.getAttribute('aria-owns', { timeout: STEP_MS }));
    const scope = listId ? page.locator(`[id="${listId.replace(/["\\]/g, '\\$&')}"]`) : page;
    const wanted = label.trim().replace(/\s+/g, ' ').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const name = new RegExp(`^${wanted}$`, 'i'); // the whole text, any case, spaces trimmed as exact: true did
    const option = scope.getByRole('option', { name }).and(page.locator('[role="option"]')).first();
    // The list renders a moment after the click; only type when it still shows no such option (search-style lists).
    const shown = await option.waitFor({ state: 'visible', timeout: 1000 }).then(() => true, () => false);
    if (!shown) await el.pressSequentially(label, { timeout: STEP_MS });
    await option.waitFor({ state: 'visible', timeout: STEP_MS });
    await clickOption(option);
    return true;
  } catch {
    // No exact option (for example a city search with longer names): close the list, leave it for the user.
    await el.press('Escape', { timeout: STEP_MS }).catch(() => {});
    await el.fill('', { timeout: STEP_MS }).catch(() => {});
    return false;
  }
}

async function setValue(
  page: Page,
  control: Control,
  field: { value: string | number | boolean; option_label?: string; labelOnly?: boolean }
): Promise<boolean> {
  const el = byTag(page, control.index);
  const label = field.option_label ?? String(field.value);
  try {
    if (control.tag === 'select') {
      // Try the visible label first (ignoring case), then the API value; saved answers match labels only.
      const labels = await el.evaluate((s) => Array.from((s as HTMLSelectElement).options).map((o) => o.label), undefined, { timeout: STEP_MS });
      const norm = (t: string) => t.trim().replace(/\s+/g, ' ').toLowerCase();
      const shown = labels.find((l) => norm(l) === norm(label)) ?? label;
      const picked = await el
        .selectOption({ label: shown }, { timeout: STEP_MS })
        .catch(() => (field.labelOnly ? [] : el.selectOption(String(field.value), { timeout: STEP_MS })));
      return picked.length > 0;
    }
    if (control.type === 'checkbox') {
      await el.setChecked(field.value === true || field.value === 'true', { timeout: STEP_MS });
      return true;
    }
    if (control.type === 'radio') return false; // radio groups: left for the user in the spike
    if (control.role === 'combobox') return await pickOption(page, el, label);
    await el.fill(label, { timeout: STEP_MS });
    return true;
  } catch {
    return false;
  }
}

export async function fillPage(page: Page, plan: FillPlan | null, profile: FillProfile, cv: Cv | null): Promise<FillResult> {
  const shown = async () => (await listControls(page)).filter((c) => c.visible && c.type !== 'hidden' && c.type !== 'submit');
  let controls = await shown();
  const used = new Set<number>();
  const result: FillResult = { planned: 0, filled: 0, unfilled: [], drafted: [], remembered: [], cvAttached: false };
  const typed: { control: Control; value: string; label: string }[] = [];

  // CV first: Lever and Greenhouse read an uploaded CV and reset fields from it, which cleared a name typed before
  // the upload (live trial, Lever in Browserbase). Let that finish before typing.
  if (cv) {
    const files = controls.filter((c) => c.type === 'file');
    const target = files.find((c) => /resume|\bcv\b|curriculum/.test(c.text)) ?? (files.length === 1 ? files[0] : undefined);
    result.planned += 1;
    if (target) {
      try {
        await byTag(page, target.index).setInputFiles(cv, { timeout: 5000 });
        result.cvAttached = true;
        result.filled += 1;
        await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {});
      } catch {
        result.unfilled.push('resume');
      }
    } else {
      result.unfilled.push('resume');
    }
    // Reading the CV can re-render the form with new elements; tag and list them again.
    controls = await shown();
  }

  // Planned answers (Greenhouse) by field name or id, before the standard matcher can claim the control.
  for (const field of plan?.fields ?? []) {
    result.planned += 1;
    const control = controls.find((c) => !used.has(c.index) && (c.name === field.name || c.id === field.name));
    if (control && (await setValue(page, control, field))) {
      used.add(control.index);
      result.filled += 1;
    } else {
      result.unfilled.push(field.label);
    }
  }

  // LLM drafts (#59) go only into their own question's free-text field, never a select or checkbox; the user
  // reviews and edits them before clicking Submit.
  for (const q of plan?.for_user ?? []) {
    if (q.draft_status !== 'generated' || !q.draft) continue;
    result.planned += 1;
    const control = controls.find((c) => !used.has(c.index) && (c.name === q.name || c.id === q.name) && freeText(c));
    if (control && (await setValue(page, control, { value: q.draft }))) {
      used.add(control.index);
      result.filled += 1;
      result.drafted.push(q.label);
    } else {
      result.unfilled.push(q.label);
    }
  }

  // Saved answers (answer memory) go only into their own question's field: text, or a dropdown when the answer is
  // one of its options. Never a checkbox, radio or file. The user reviews them before clicking Submit.
  for (const q of plan?.for_user ?? []) {
    if (!q.memory_answer) continue;
    result.planned += 1;
    const control = controls.find(
      (c) => !used.has(c.index) && (c.name === q.name || c.id === q.name) && (freeText(c) || c.tag === 'select' || c.role === 'combobox')
    );
    if (control && (await setValue(page, control, { value: q.memory_answer, option_label: q.memory_answer, labelOnly: true }))) {
      used.add(control.index);
      result.filled += 1;
      result.remembered.push({ label: q.label, similar: q.memory_match === 'similar' });
    } else {
      result.unfilled.push(q.label);
    }
  }

  const values = standardValues(profile);
  const done = new Set<StandardKey>(); // full_name has two rules; fill it once
  for (const [key, matches] of STANDARD) {
    const value = values[key];
    if (!value || done.has(key)) continue;
    const control = controls.find((c) => !used.has(c.index) && c.type !== 'file' && standardField(c) && matches(c));
    if (!control) continue;
    result.planned += 1;
    used.add(control.index);
    done.add(key);
    if (await setValue(page, control, { value })) {
      result.filled += 1;
      if (control.role !== 'combobox' && control.tag !== 'select') typed.push({ control, value, label: key });
    } else {
      result.unfilled.push(key);
    }
  }

  // A late CV read can still clear typed fields; check once and type them again.
  await page.waitForTimeout(1000);
  for (const t of typed) {
    const el = byTag(page, t.control.index);
    if ((await el.inputValue({ timeout: STEP_MS }).catch(() => t.value)) !== '') continue;
    if (!(await setValue(page, t.control, { value: t.value }))) {
      result.filled -= 1;
      result.unfilled.push(t.label);
    }
  }
  return result;
}
