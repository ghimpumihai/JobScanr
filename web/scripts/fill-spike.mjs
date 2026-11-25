// Stage 2 of the remote-browser apply spike (#129, Task 6.1): fills real application forms with a fake person in each
// remote provider (Browserbase, Cloudflare Browser Run) and in a local visible browser (the home-connection
// baseline), and never submits.
// Records load and fill time, required fields filled, the CV, and whether a captcha challenge is visible.
// Live. Usage (from web/, with ../.env exported):
//   node scripts/fill-spike.mjs --confirm-live <postings.json> [--browsers browserbase,cloudflare,local] [--limit N]
// postings.json comes from `python -m scripts.spike_postings --confirm-live --out ...`.
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { chromium } from 'playwright-core';

// Fake person only: no real user data leaves the machine. example.com is reserved; the number is a drama number.
export const PERSONA = {
  full_name: 'Jane Doe',
  email: 'jane.doe.test@example.com',
  phone: '+44 7700 900000',
  location: 'London, UK',
  linkedin: 'https://www.linkedin.com/in/example',
  github: 'https://github.com/example',
  portfolio: 'https://example.com'
};
const PDF = '%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n';
export const dummyCv = () => ({ name: 'Jane Doe CV.pdf', mimeType: 'application/pdf', buffer: Buffer.from(PDF) });

// Second guard on top of fill.ts never clicking Submit: native form submission is cancelled in every frame.
export const NO_SUBMIT = () =>
  document.addEventListener(
    'submit',
    (e) => {
      e.preventDefault();
      e.stopImmediatePropagation();
      window.__jobscanrBlockedSubmit = true;
    },
    true
  );

/** Loads the form with `load`, fills it, and reads what landed where. Never throws; failures are recorded. */
export async function measure(page, load, { fillPage, captchaVisible }, plan = null) {
  const started = Date.now();
  try {
    await load(page);
    await page.locator('input, textarea, select').first().waitFor({ state: 'attached', timeout: 20_000 });
  } catch (e) {
    return { formFound: false, loadMs: Date.now() - started, error: e?.name ?? 'Error' };
  }
  const loadMs = Date.now() - started;
  const fillStart = Date.now();
  let result;
  try {
    result = await fillPage(page, plan, PERSONA, dummyCv());
  } catch (e) {
    return { formFound: true, loadMs, error: e?.name ?? 'Error' };
  }
  const fillMs = Date.now() - fillStart;
  const captcha = await captchaVisible(page);
  const read = await page.locator('input, textarea, select').evaluateAll((els) => {
    const shown = (e) => e.type === 'file' || (e.offsetParent !== null && getComputedStyle(e).visibility !== 'hidden');
    const label = (e) =>
      ([...(e.labels ?? [])].map((l) => l.textContent).join(' ') || e.getAttribute('aria-label') || e.name || e.id || '')
        .replace(/\s+/g, ' ')
        .trim()
        .slice(0, 80);
    const filled = (e) =>
      e.type === 'file' ? e.files.length > 0 : e.type === 'checkbox' || e.type === 'radio' ? e.checked : Boolean(e.value);
    const required = (e) =>
      e.required || e.getAttribute('aria-required') === 'true' || /[*✱]/.test([...(e.labels ?? [])].map((l) => l.textContent).join(''));
    const controls = els.filter((e) => e.type !== 'hidden' && e.type !== 'submit' && shown(e));
    // Radio and checkbox groups count once per name.
    const seen = new Set();
    const unique = controls.filter((e) => {
      if (e.type !== 'radio' && e.type !== 'checkbox') return true;
      const key = `${e.type}:${e.name}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
    const groupFilled = (e) =>
      e.type === 'radio' || e.type === 'checkbox'
        ? controls.some((c) => c.type === e.type && c.name === e.name && c.checked)
        : filled(e);
    const req = unique.filter(required);
    return {
      requiredTotal: req.length,
      requiredFilled: req.filter(groupFilled).length,
      requiredEmpty: req.filter((e) => !groupFilled(e)).map(label),
      // Fake persona values only, for checking each value landed in the right field.
      filledFields: controls
        .filter((e) => e.type !== 'checkbox' && e.type !== 'radio' && filled(e))
        .map((e) => [label(e), e.type === 'file' ? [...e.files].map((f) => f.name).join(',') : String(e.value).slice(0, 60)])
    };
  });
  const blockedSubmit = await page.evaluate(() => Boolean(window.__jobscanrBlockedSubmit)).catch(() => false);
  return { formFound: true, loadMs, fillMs, ...result, captcha, ...read, blockedSubmit };
}

export const BROWSERS = ['browserbase', 'cloudflare', 'local'];
// Cloudflare's free plan starts at most one new browser every 20 seconds.
const MIN_GAP_MS = { cloudflare: 20_000 };

export function parseArgs(argv) {
  const args = { browsers: BROWSERS, limit: Infinity, file: null };
  if (argv[0] !== '--confirm-live') return null;
  for (let i = 1; i < argv.length; i += 1) {
    if (argv[i] === '--browsers') {
      const list = (argv[++i] ?? '').split(',').filter(Boolean);
      if (!list.length || list.some((b) => !BROWSERS.includes(b))) return null;
      args.browsers = list;
    }
    else if (argv[i] === '--limit' && /^\d+$/.test(argv[i + 1] ?? '')) args.limit = Number(argv[++i]);
    else if (!argv[i].startsWith('--') && !args.file) args.file = argv[i];
    else return null;
  }
  return args.file ? args : null;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args) {
    console.error('Refusing to run: node scripts/fill-spike.mjs --confirm-live <postings.json> [--browsers browserbase,cloudflare,local] [--limit N]');
    process.exit(2);
  }
  const { createServer } = await import('vite');
  const vite = await createServer({ server: { middlewareMode: true, ws: false }, logLevel: 'error' });
  const engine = {
    ...(await vite.ssrLoadModule('/src/lib/server/remoteApply/fill.ts')),
    ...(await vite.ssrLoadModule('/src/lib/server/remoteApply/detect.ts'))
  };
  const { formUrl } = await vite.ssrLoadModule('/src/lib/server/remoteApply/session.ts');
  const { getProvider } = await vite.ssrLoadModule('/src/lib/server/remoteApply/provider.ts');

  const postings = JSON.parse(readFileSync(args.file, 'utf8')).slice(0, args.limit);
  const outDir = new URL(`../.spike-results/${new Date().toISOString().replace(/[:.]/g, '-')}/`, import.meta.url);
  mkdirSync(outDir, { recursive: true });
  const results = [];
  const local = args.browsers.includes('local') ? await chromium.launch({ headless: false }) : null;
  const providers = Object.fromEntries(args.browsers.filter((b) => b !== 'local').map((b) => [b, getProvider(b)]));
  const lastStart = {};

  try {
    for (const [i, p] of postings.entries()) {
      const url = formUrl(p.platform, p, p.plan);
      if (!url) {
        results.push({ ...p, plan: undefined, browser: 'none', error: 'no form url' });
        continue;
      }
      const load = (page) => page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30_000 });
      for (const where of args.browsers) {
        const provider = providers[where];
        if (where !== 'local' && !provider) continue; // stopped earlier in this run (no free time left)
        let session;
        let browser;
        let context;
        try {
          if (provider) {
            const wait = (lastStart[where] ?? 0) + (MIN_GAP_MS[where] ?? 0) - Date.now();
            if (wait > 0) await new Promise((r) => setTimeout(r, wait));
            lastStart[where] = Date.now();
            session = await provider.create();
            browser = await chromium.connectOverCDP(session.connection.url, { headers: session.connection.headers });
            context = browser.contexts()[0];
          } else {
            context = await local.newContext(); // fresh cookies, like a new visitor
          }
          await context.addInitScript(NO_SUBMIT);
          const page = context.pages()[0] ?? (await context.newPage());
          const r = await measure(page, load, engine, p.plan ?? null);
          const shot = fileURLToPath(new URL(`${String(i).padStart(2, '0')}-${p.platform}-${where}.png`, outDir));
          await page.screenshot({ path: shot, fullPage: true }).catch((e) => console.log(`  no screenshot (${e?.name})`));
          results.push({ platform: p.platform, url, browser: where, ...r });
          console.log(`${i + 1}/${postings.length} ${p.platform} ${where}: ${r.formFound ? `${r.requiredFilled}/${r.requiredTotal} required, captcha=${r.captcha}` : `no form (${r.error})`}`);
        } catch (e) {
          // Connection errors can contain the connect key; record the error's name only.
          const quota = e?.status === 429;
          results.push({ platform: p.platform, url, browser: where, error: quota ? 'quota' : (e?.name ?? 'Error') });
          console.log(`${i + 1}/${postings.length} ${p.platform} ${where}: ${quota ? 'no free time left, skipped for the rest of this run' : `failed (${e?.name ?? 'Error'})`}`);
          if (quota) delete providers[where];
        } finally {
          if (where === 'local') await context?.close().catch(() => {});
          await browser?.close().catch(() => {});
          if (session) await provider.release(session.id).catch(() => {}); // provider is still bound here
        }
        await new Promise((r) => setTimeout(r, 2000)); // one page at a time, paced
      }
      writeFileSync(new URL('results.json', outDir), JSON.stringify(results, null, 1)); // kept if the run stops early
    }
  } finally {
    await local?.close();
    await vite.close();
  }
  console.log(`Results: ${fileURLToPath(new URL('results.json', outDir))}`);
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) await main();
