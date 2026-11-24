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

export interface FillPlan {
  version: number;
  platform: string;
  posting_url: string | null;
  fields: PlanField[];
  for_user: { name: string; label: string; reason: string }[];
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
  visible: boolean;
}

const CONTROLS = 'input, textarea, select';

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

async function listControls(page: Page): Promise<Control[]> {
  return page.locator(CONTROLS).evaluateAll((els) =>
    els.map((el, index) => {
      const e = el as HTMLInputElement;
      const labels = Array.from(e.labels ?? []).map((l) => l.textContent ?? '');
      const labelledBy = (e.getAttribute('aria-labelledby') ?? '')
        .split(/\s+/)
        .map((id) => (id ? document.getElementById(id)?.textContent ?? '' : ''));
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
        // File inputs are usually hidden behind a styled button; they still accept files.
        visible: e.type === 'file' || (style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0)
      };
    })
  );
}

/** Refuses to click anything that could submit the form. */
async function clickOption(option: Locator): Promise<void> {
  const unsafe = await option.evaluate((el) => {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') ?? '').toLowerCase();
    return tag === 'button' || type === 'submit' || type === 'image' || el.getAttribute('role') !== 'option';
  });
  if (unsafe) throw new Error('refusing to click a control that is not a dropdown option');
  await option.click({ timeout: 2000 });
}

async function setValue(page: Page, control: Control, field: { value: string | number | boolean; option_label?: string }): Promise<boolean> {
  const el = page.locator(CONTROLS).nth(control.index);
  const label = field.option_label ?? String(field.value);
  try {
    if (control.tag === 'select') {
      // Try the visible label first, then the API value.
      const picked = await el.selectOption({ label }, { timeout: 2000 }).catch(() => el.selectOption(String(field.value), { timeout: 2000 }));
      return picked.length > 0;
    }
    if (control.type === 'checkbox') {
      await el.setChecked(field.value === true || field.value === 'true', { timeout: 2000 });
      return true;
    }
    if (control.type === 'radio') return false; // radio groups: left for the user in the spike
    await el.fill(label, { timeout: 2000 });
    if (control.role === 'combobox') {
      await clickOption(page.getByRole('option', { name: label, exact: true }).first());
    }
    return true;
  } catch {
    return false;
  }
}

export async function fillPage(page: Page, plan: FillPlan | null, profile: FillProfile, cv: Cv | null): Promise<FillResult> {
  const controls = (await listControls(page)).filter((c) => c.visible && c.type !== 'hidden' && c.type !== 'submit');
  const used = new Set<number>();
  const result: FillResult = { planned: 0, filled: 0, unfilled: [], cvAttached: false };

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

  const values = standardValues(profile);
  const done = new Set<StandardKey>(); // full_name has two rules; fill it once
  for (const [key, matches] of STANDARD) {
    const value = values[key];
    if (!value || done.has(key)) continue;
    const control = controls.find((c) => !used.has(c.index) && c.type !== 'file' && matches(c));
    if (!control) continue;
    result.planned += 1;
    used.add(control.index);
    done.add(key);
    if (await setValue(page, control, { value })) result.filled += 1;
    else result.unfilled.push(key);
  }

  if (cv) {
    const files = controls.filter((c) => c.type === 'file');
    const target = files.find((c) => /resume|\bcv\b|curriculum/.test(c.text)) ?? (files.length === 1 ? files[0] : undefined);
    result.planned += 1;
    if (target) {
      try {
        await page.locator(CONTROLS).nth(target.index).setInputFiles(cv, { timeout: 5000 });
        result.cvAttached = true;
        result.filled += 1;
      } catch {
        result.unfilled.push('resume');
      }
    } else {
      result.unfilled.push('resume');
    }
  }
  return result;
}
