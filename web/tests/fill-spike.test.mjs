// Stage 2 runner (#129): its guard and its measurement, offline in local Chromium with all network blocked.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { after, before, test } from 'node:test';
import { chromium } from 'playwright-core';
import { createServer } from 'vite';
import { BROWSERS, measure, NO_SUBMIT, parseArgs, PERSONA } from '../scripts/fill-spike.mjs';

const vite = await createServer({ server: { middlewareMode: true, ws: false }, logLevel: 'error' });
const engine = {
  ...(await vite.ssrLoadModule('/src/lib/server/remoteApply/fill.ts')),
  ...(await vite.ssrLoadModule('/src/lib/server/remoteApply/detect.ts'))
};
let browser;
before(async () => {
  browser = await chromium.launch();
});
after(async () => {
  await browser?.close();
  await vite.close();
});

async function page() {
  const p = await browser.newPage();
  await p.route('**', (route) => route.abort());
  return p;
}

test('refuses to run without --confirm-live, or with unknown flags, before touching the network', () => {
  for (const args of [[], ['postings.json'], ['--confirm-live'], ['--confirm-live', 'p.json', '--browsers', 'browserbase,nope']]) {
    const run = spawnSync(process.execPath, ['scripts/fill-spike.mjs', ...args], { encoding: 'utf8' });
    assert.equal(run.status, 2, `args ${args.join(' ')}`);
    assert.match(run.stderr, /Refusing to run/);
  }
});

test('parseArgs: all three browsers by default, or a chosen subset', () => {
  assert.deepEqual(parseArgs(['--confirm-live', 'p.json']).browsers, BROWSERS);
  assert.deepEqual(parseArgs(['--confirm-live', 'p.json', '--browsers', 'cloudflare,local', '--limit', '3']), {
    browsers: ['cloudflare', 'local'],
    limit: 3,
    file: 'p.json'
  });
  assert.equal(parseArgs(['--confirm-live', 'p.json', '--browsers', '']), null);
});

test('measure: counts required fields, lists what landed where, and the fake CV', async () => {
  const p = await page();
  const form = `<form>
    <label for="f">First Name*</label><input id="f" required>
    <label for="l">Last Name*</label><input id="l" required>
    <label for="e">Email*</label><input id="e" type="email" required>
    <label for="w">Why us?*</label><textarea id="w" required></textarea>
    <label for="r">Resume*</label><input id="r" type="file" required>
    <fieldset><legend>Authorized?</legend>
      <input type="radio" name="auth" id="a1" aria-required="true"><label for="a1">Yes</label>
      <input type="radio" name="auth" id="a2"><label for="a2">No</label></fieldset>
    <button type="submit">Submit</button></form>`;
  const r = await measure(p, (pg) => pg.setContent(form), engine);

  assert.equal(r.formFound, true);
  assert.equal(r.requiredTotal, 6); // the radio group counts once
  assert.equal(r.requiredFilled, 4);
  assert.deepEqual(r.requiredEmpty.sort(), ['Why us?*', 'Yes']);
  assert.deepEqual(Object.fromEntries(r.filledFields), {
    'First Name*': 'Jane',
    'Last Name*': 'Doe',
    'Email*': PERSONA.email,
    'Resume*': 'Jane Doe CV.pdf'
  });
  assert.equal(r.cvAttached, true);
  assert.equal(r.captcha, false);
  assert.equal(r.blockedSubmit, false); // nothing tried to submit
  await p.close();
});

test('measure: a page that never shows a form is recorded, not thrown', async () => {
  const p = await page();
  const r = await measure(
    p,
    async () => {
      throw Object.assign(new Error('net'), { name: 'TimeoutError' });
    },
    engine
  );
  assert.deepEqual(r.formFound, false);
  assert.equal(r.error, 'TimeoutError');
  await p.close();
});

test('NO_SUBMIT cancels a form submission and records the attempt', async () => {
  const p = await page();
  await p.setContent('<form action="https://example.com/apply"><input name="x"><button>Submit</button></form>');
  await p.evaluate(NO_SUBMIT);
  await p.click('button');
  assert.equal(await p.evaluate(() => window.__jobscanrBlockedSubmit), true);
  assert.equal(p.url(), 'about:blank'); // still here: the request never left
  await p.close();
});
