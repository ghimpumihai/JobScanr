// Fill engine against local forms in a real headless Chromium, with every network request blocked (#129).
// Synthetic forms shaped like each ATS for now; Task 3.4 adds saved copies of real apply pages to fixtures/apply/.
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, existsSync } from 'node:fs';
import { after, before, test } from 'node:test';
import { chromium } from 'playwright-core';
import { createServer } from 'vite';

const vite = await createServer({ server: { middlewareMode: true, ws: false }, logLevel: 'error' });
const { fillPage } = await vite.ssrLoadModule('/src/lib/server/remoteApply/fill.ts');
const { captchaVisible, isConfirmation } = await vite.ssrLoadModule('/src/lib/server/remoteApply/detect.ts');

let browser;
before(async () => {
  browser = await chromium.launch();
});
after(async () => {
  await browser?.close();
  await vite.close();
});

const PROFILE = {
  full_name: 'Jane Q Doe',
  email: 'jane@example.com',
  phone: '+44 7000 000000',
  location: 'London, UK',
  linkedin: 'https://linkedin.com/in/jane',
  github: 'https://github.com/jane'
};
const CV = { name: 'Jane Doe CV.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 test') };

// Any submit attempt (button click, Enter, form.submit) flips window.__submitted.
const TRAP = `<script>
  window.__submitted = false;
  document.addEventListener('submit', (e) => { e.preventDefault(); window.__submitted = true; }, true);
  document.addEventListener('click', (e) => { if (e.target.closest('button,[type=submit]')) window.__submitted = true; }, true);
</script>`;

async function open(html) {
  const page = await browser.newPage();
  await page.route('**', (route) => route.abort()); // nothing may leave the machine
  await page.setContent(html + TRAP);
  return page;
}

const GREENHOUSE = `<form>
  <label for="first_name">First Name</label><input id="first_name" name="first_name">
  <label for="last_name">Last Name</label><input id="last_name" name="last_name">
  <label for="email">Email</label><input id="email" name="email" type="email">
  <label for="phone">Phone</label><input id="phone" name="phone" type="tel">
  <label for="resume">Resume/CV</label><input id="resume" type="file">
  <label for="question_1">Are you legally authorized to work?</label>
  <select id="question_1" name="question_1"><option value="">--</option><option value="1">Yes</option><option value="0">No</option></select>
  <label for="question_2">Will you require visa sponsorship?</label><input id="question_2" name="question_2">
  <label for="question_3">LinkedIn Profile</label><input id="question_3" name="question_3">
  <label for="question_4">Why Acme?</label><textarea id="question_4" name="question_4"></textarea>
  <button type="submit">Submit application</button>
</form>`;

const GH_PLAN = {
  version: 1,
  platform: 'greenhouse',
  posting_url: 'https://job-boards.greenhouse.io/acme/jobs/1',
  fields: [
    { name: 'question_1', label: 'Are you legally authorized to work?', type: 'single_select', value: 1, option_label: 'Yes' },
    { name: 'question_2', label: 'Will you require visa sponsorship?', type: 'short_text', value: 'No' },
    { name: 'question_3', label: 'LinkedIn Profile', type: 'short_text', value: 'https://linkedin.com/in/jane' },
    { name: 'question_9', label: 'Removed since the plan was built', type: 'short_text', value: 'x' }
  ],
  for_user: [{ name: 'question_4', label: 'Why Acme?', reason: 'open_ended' }]
};

test('Greenhouse-shaped form: planned answers by name, standard fields by label, CV attached, nothing submitted', async () => {
  const page = await open(GREENHOUSE);
  const result = await fillPage(page, GH_PLAN, PROFILE, CV);
  const value = (sel) => page.inputValue(sel);

  assert.equal(await value('#first_name'), 'Jane');
  assert.equal(await value('#last_name'), 'Q Doe');
  assert.equal(await value('#email'), 'jane@example.com');
  assert.equal(await value('#phone'), '+44 7000 000000');
  assert.equal(await value('#question_1'), '1');
  assert.equal(await value('#question_2'), 'No');
  assert.equal(await value('#question_3'), 'https://linkedin.com/in/jane'); // planned, not claimed twice
  assert.equal(await value('#question_4'), ''); // open-ended: left for the user
  assert.deepEqual(await page.$eval('#resume', (el) => [...el.files].map((f) => f.name)), ['Jane Doe CV.pdf']);
  assert.equal(result.cvAttached, true);
  assert.deepEqual(result.unfilled, ['Removed since the plan was built']); // a missing field is reported, not guessed
  assert.equal(await page.evaluate(() => window.__submitted), false);
  await page.close();
});

test('Lever-shaped form: single name field and URL fields, no plan', async () => {
  const page = await open(`<form>
    <label>Full name<input name="name"></label>
    <label>Email<input name="email" type="email"></label>
    <label>Phone<input name="phone"></label>
    <label>Current company<input name="org"></label>
    <label>LinkedIn URL<input name="urls[LinkedIn]"></label>
    <label>GitHub URL<input name="urls[GitHub]"></label>
    <label>Resume/CV<input type="file" name="resume" style="display:none"></label>
    <button type="submit">Submit application</button></form>`);
  const result = await fillPage(page, null, PROFILE, CV);

  assert.equal(await page.inputValue('[name=name]'), 'Jane Q Doe');
  assert.equal(await page.inputValue('[name=org]'), ''); // "company" never gets the person's name
  assert.equal(await page.inputValue('[name="urls[LinkedIn]"]'), 'https://linkedin.com/in/jane');
  assert.equal(await page.inputValue('[name="urls[GitHub]"]'), 'https://github.com/jane');
  assert.equal(result.cvAttached, true); // hidden file inputs still take the file
  assert.equal(await page.evaluate(() => window.__submitted), false);
  await page.close();
});

test('Ashby-shaped form: a combobox option is clicked, never a button', async () => {
  const page = await open(`<form>
    <label for="n">Name</label><input id="n" name="_systemfield_name">
    <label for="e">Email</label><input id="e" name="_systemfield_email">
    <label for="loc">Location</label><input id="loc" role="combobox" aria-controls="opts">
    <ul id="opts"><li role="option" onclick="document.getElementById('loc').dataset.picked = this.textContent">London, UK</li></ul>
    <label for="r">Resume</label><input id="r" type="file" name="_systemfield_resume">
    <button type="submit">Submit Application</button></form>`);
  await fillPage(page, null, PROFILE, CV);

  assert.equal(await page.inputValue('#n'), 'Jane Q Doe');
  assert.equal(await page.$eval('#loc', (el) => el.dataset.picked), 'London, UK');
  assert.equal(await page.evaluate(() => window.__submitted), false);
  await page.close();
});

// Labels from saved real forms that the first matcher got wrong (Task 3.4 audit, 2026-11-23).
test('real-form labels: one field for first and last name, ethnicity is not a city, a different legal name and a major stay empty', async () => {
  const page = await open(`<form>
    <label for="fl">First and Last Name</label><input id="fl" name="_systemfield_name">
    <label for="eth">Are you Hispanic/Latino?</label><input id="eth" name="hispanic_ethnicity" role="combobox">
    <label for="loc">Location (City)</label><input id="loc" name="candidate-location">
    <label for="legal">Legal Name (if different than above)</label><input id="legal" name="question_9">
    <label for="major">Please share the full name of your major/field of study</label><input id="major" name="question_10">
    <button type="submit">Submit</button></form>`);
  await fillPage(page, null, PROFILE, null);
  assert.equal(await page.inputValue('#fl'), 'Jane Q Doe');
  assert.equal(await page.inputValue('#eth'), '');
  assert.equal(await page.inputValue('#loc'), 'London, UK');
  assert.equal(await page.inputValue('#legal'), '');
  assert.equal(await page.inputValue('#major'), '');
  assert.equal(await page.evaluate(() => window.__submitted), false);
  await page.close();
});

// Live trial 2026-11-25: Greenhouse dropdowns insert inputs while filling, which moved positional lookups onto the
// wrong fields (Phone got the city), and each unmatched dropdown waited Playwright's 30 s default.
test('inputs inserted mid-fill never shift values into the wrong fields', async () => {
  const page = await open(`<form>
    <label for="q1">Are you authorized to work?</label><input id="q1" name="question_1" role="combobox" aria-controls="m1">
    <ul id="m1" hidden><li role="option">Yes</li><li role="option">No</li></ul>
    <label for="first">First Name</label><input id="first">
    <label for="phone">Phone</label><input id="phone" type="tel">
    <label for="loc">Location (City)</label><input id="loc" role="combobox">
    <button type="submit">Submit</button></form>
    <script>
      const q1 = document.getElementById('q1'), m1 = document.getElementById('m1');
      q1.addEventListener('click', () => {
        m1.hidden = false;
        // like react-select: a new input appears before the remaining fields
        q1.insertAdjacentHTML('afterend', '<input aria-hidden="true" style="width:1px">');
      });
      m1.addEventListener('click', (e) => { q1.value = e.target.textContent; m1.hidden = true; });
    </script>`);
  const plan = { ...GH_PLAN, fields: [{ name: 'question_1', label: 'Are you authorized to work?', type: 'single_select', value: 1, option_label: 'Yes' }] };
  const started = Date.now();
  const result = await fillPage(page, plan, PROFILE, null);

  assert.equal(await page.inputValue('#q1'), 'Yes'); // opened with a click, exact option picked
  assert.equal(await page.inputValue('#first'), 'Jane');
  assert.equal(await page.inputValue('#phone'), '+44 7000 000000'); // not the city
  assert.equal(await page.inputValue('#loc'), ''); // no exact option: cleared and left for the user
  assert.ok(result.unfilled.includes('location'));
  assert.ok(Date.now() - started < 15_000, `took ${Date.now() - started} ms`); // bounded waits, not 30 s each
  assert.equal(await page.evaluate(() => window.__submitted), false);
  await page.close();
});

// Live trial 2026-11-25: Lever read the uploaded CV and emptied "Full name" after it had been typed.
test('a page that clears fields after the CV upload, or a moment later, still ends up filled', async () => {
  const page = await open(`<form>
    <label for="r">Resume/CV</label><input id="r" type="file" name="resume">
    <label for="n">Full name</label><input id="n" name="name">
    <label for="e">Email</label><input id="e" type="email" name="email">
    <button type="submit">Submit</button></form>
    <script>
      const n = document.getElementById('n');
      document.getElementById('r').addEventListener('change', () => setTimeout(() => (n.value = ''), 200));
      let cleared = false; // and once more, shortly after the name was first typed
      n.addEventListener('input', () => { if (!cleared && n.value) { cleared = true; setTimeout(() => (n.value = ''), 300); } });
    </script>`);
  const result = await fillPage(page, null, PROFILE, CV);
  assert.equal(await page.inputValue('#n'), 'Jane Q Doe');
  assert.equal(await page.inputValue('#e'), 'jane@example.com');
  assert.equal(result.cvAttached, true);
  assert.deepEqual(result.unfilled, []);
  assert.equal(await page.evaluate(() => window.__submitted), false);
  await page.close();
});

test('a page with no recognisable fields fills nothing and reports the CV as unfilled', async () => {
  const page = await open('<form><input name="q1"><button type="submit">Go</button></form>');
  const result = await fillPage(page, null, PROFILE, CV);
  assert.equal(result.filled, 0);
  assert.deepEqual(result.unfilled, ['resume']);
  assert.equal(await page.evaluate(() => window.__submitted), false);
  await page.close();
});

test('captchaVisible is false on a page without challenge frames', async () => {
  const page = await open(GREENHOUSE);
  assert.equal(await captchaVisible(page), false);
  await page.close();
});

test('isConfirmation matches only the platform rule', () => {
  assert.equal(isConfirmation('greenhouse', 'https://job-boards.greenhouse.io/acme/jobs/1/confirmation', ''), true);
  assert.equal(isConfirmation('greenhouse', 'https://job-boards.greenhouse.io/acme/jobs/1', 'Apply for this job'), false);
  assert.equal(isConfirmation('lever', 'https://jobs.lever.co/acme/abc/thanks', ''), true);
  assert.equal(isConfirmation('workday', 'https://x/thanks', 'thanks for applying'), false); // unsupported platform
});

// Saved real apply pages (Task 3.4): every one must expose the standard fields and take the CV.
const FIXTURES = new URL('./fixtures/apply/', import.meta.url);
for (const file of existsSync(FIXTURES) ? readdirSync(FIXTURES).filter((f) => f.endsWith('.html')) : []) {
  test(`saved page ${file}: standard fields and CV fill, nothing submitted`, async () => {
    const page = await open(readFileSync(new URL(file, FIXTURES), 'utf8'));
    const result = await fillPage(page, null, PROFILE, CV);
    assert.ok(result.filled >= 3, `only ${result.filled} field(s) filled: ${result.unfilled.join(', ')}`);
    assert.equal(result.cvAttached, true);
    assert.equal(await page.evaluate(() => window.__submitted), false);
    await page.close();
  });
}

test('the submit trap itself catches a click on Submit', async () => {
  const page = await open(GREENHOUSE);
  await page.click('button');
  assert.equal(await page.evaluate(() => window.__submitted), true);
  await page.close();
});
