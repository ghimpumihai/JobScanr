// Read-only checks on the remote page (#129, spike). Nothing here clicks or types.
import type { Page } from 'playwright-core';

// Challenge frames only: reCAPTCHA's invisible anchor and Turnstile's invisible mode have no visible size.
const CHALLENGE_FRAMES = [/google\.com\/recaptcha\/.*\/bframe/, /recaptcha\.net\/recaptcha\/.*\/bframe/, /hcaptcha\.com\/.*frame=challenge/, /challenges\.cloudflare\.com/];

/** True when a captcha challenge is on screen (a visible frame from a captcha provider). */
export async function captchaVisible(page: Page): Promise<boolean> {
  for (const frame of page.frames()) {
    if (!CHALLENGE_FRAMES.some((re) => re.test(frame.url()))) continue;
    // Challenge frames are often in the page all along, hidden until needed; only a shown one counts.
    const el = await frame.frameElement().catch(() => null);
    if (el && (await el.isVisible().catch(() => false))) {
      const box = await el.boundingBox().catch(() => null);
      if (box && box.width > 30 && box.height > 30) return true;
    }
  }
  return false;
}

// shortcut: placeholder patterns, not yet checked against real confirmation pages; replace them in Task 6.3
// from public documentation or employer-consented submissions, never by submitting to a real employer.
const CONFIRMATION: Record<string, { url?: RegExp; text?: RegExp }> = {
  greenhouse: { url: /\/confirmation\b/, text: /thank you for applying|application (has been )?(received|submitted)/i },
  lever: { url: /\/thanks\b/, text: /application submitted|thanks for applying/i },
  ashby: { text: /application (was )?submitted|thanks for applying|we have received your application/i }
};

/**
 * True when the URL matches the platform's confirmation page, or its text matches and the application form is gone
 * (`formPresent` false): a form or posting page can itself contain words like "thanks for applying".
 */
export function isConfirmation(platform: string, url: string, text: string, formPresent: boolean): boolean {
  const rule = CONFIRMATION[platform];
  if (!rule) return false;
  return Boolean((rule.url && rule.url.test(url)) || (!formPresent && rule.text && rule.text.test(text)));
}
