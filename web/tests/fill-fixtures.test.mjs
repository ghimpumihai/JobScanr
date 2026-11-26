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

test('LLM drafts go only into their own free-text field and are never submitted (#59)', async () => {
  const page = await open(`<form>
    <label for="question_4">Why Acme?</label><textarea id="question_4" name="question_4"></textarea>
    <label for="question_5">Tell us about a project</label><input id="question_5" name="question_5">
    <label for="question_6">Pick one</label><select id="question_6" name="question_6"><option value="">--</option><option>I build payments.</option></select>
    <label for="question_7">Notes</label><textarea id="question_7" name="question_7"></textarea>
    <label for="cover">Anything else?</label><textarea id="cover" name="cover"></textarea>
    <button type="submit">Submit</button>
  </form>`);
  const draft = (name, label, extra = {}) => ({ name, label, reason: 'open_ended', type: 'long_text', draft: `Draft for ${label}.`, draft_status: 'generated', ...extra });
  const plan = {
    ...GH_PLAN,
    fields: [],
    for_user: [
      draft('question_4', 'Why Acme?'),
      draft('question_5', 'Tell us about a project'),
      draft('question_6', 'Pick one'), // not free text: never typed
      draft('question_7', 'Notes', { draft: undefined, draft_status: 'unanswered', draft_reason: 'rate_limit_exceeded' }),
      draft('question_99', 'Removed from the form')
    ]
  };
  const result = await fillPage(page, plan, {}, null);
  assert.equal(await page.inputValue('#question_4'), 'Draft for Why Acme?.');
  assert.equal(await page.inputValue('#question_5'), 'Draft for Tell us about a project.');
  assert.equal(await page.inputValue('#question_6'), '');
  assert.equal(await page.inputValue('#question_7'), '');
  assert.equal(await page.inputValue('#cover'), '');
  assert.deepEqual(result.drafted, ['Why Acme?', 'Tell us about a project']);
  assert.deepEqual(result.unfilled, ['Pick one', 'Removed from the form']);
  assert.equal(result.planned, 4);
  assert.equal(await page.evaluate(() => window.__submitted), false);
  await page.close();
});

test('saved answers go only into their own field; dropdowns only on an option match, any case (answer memory)', async () => {
  const page = await open(`<form>
    <label for="question_7">Salary expectations</label><input id="question_7" name="question_7">
    <label for="question_8">Willing to relocate?</label><select id="question_8" name="question_8"><option value="">--</option><option value="1">Yes</option><option value="0">No</option></select>
    <label for="question_9">Work arrangement</label><select id="question_9" name="question_9"><option value="">--</option><option>Remote</option><option>Hybrid</option></select>
    <label for="question_10">I consent</label><input id="question_10" name="question_10" type="checkbox">
    <label for="question_11">Years of experience</label><select id="question_11" name="question_11"><option value="">--</option><option value="1">0-1</option><option value="2">1-3</option><option value="3">3-5</option></select>
    <label for="other">Anything else?</label><textarea id="other" name="other"></textarea>
    <button type="submit">Submit</button>
  </form>`);
  const saved = (name, label, memory_answer, memory_match = 'exact') => ({ name, label, reason: 'no_confident_answer', memory_answer, memory_match });
  const plan = {
    ...GH_PLAN,
    fields: [],
    for_user: [
      saved('question_7', 'Salary expectations', '60,000 EUR', 'similar'),
      saved('question_8', 'Willing to relocate?', 'yes'),
      saved('question_9', 'Work arrangement', 'On site'), // not an option: left
      saved('question_10', 'I consent', 'yes'), // checkbox: never
      saved('question_11', 'Years of experience', '3'), // equals an option's value, not its label: left
      { name: 'other', label: 'Anything else?', reason: 'no_confident_answer' } // nothing saved
    ]
  };
  const result = await fillPage(page, plan, {}, null);
  assert.equal(await page.inputValue('#question_7'), '60,000 EUR');
  assert.equal(await page.inputValue('#question_8'), '1');
  assert.equal(await page.inputValue('#question_9'), '');
  assert.equal(await page.isChecked('#question_10'), false);
  assert.equal(await page.inputValue('#question_11'), '');
  assert.equal(await page.inputValue('#other'), '');
  assert.deepEqual(result.remembered, [{ label: 'Salary expectations', similar: true }, { label: 'Willing to relocate?', similar: false }]);
  assert.deepEqual(result.unfilled, ['Work arrangement', 'I consent', 'Years of experience']);
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

test('a server-rendered form is filled only once its scripts have loaded (#137)', async () => {
  // Like Greenhouse in a slow remote browser: the dropdown is in the page at once, but it opens only after the page's
  // script (here a fetch held back for 1.5 s) has run.
  const page = await browser.newPage();
  await page.route('**', async (route) => {
    if (!route.request().url().endsWith('/app.js')) return route.abort();
    await new Promise((r) => setTimeout(r, 1500));
    await route.fulfill({ contentType: 'text/javascript', body: '' });
  });
  await page.setContent(
    `<form><label for="q1">Authorized to work</label><input id="q1" name="question_1" role="combobox" aria-controls="m1">
      <ul id="m1" hidden><li role="option" onclick="document.getElementById('q1').dataset.picked = this.textContent">Yes</li></ul></form>
    <script>
      fetch('https://form.test/app.js').then(() => {
        document.getElementById('q1').addEventListener('click', () => { document.getElementById('m1').hidden = false; });
      });
    </script>${TRAP}`,
    { waitUntil: 'domcontentloaded' }
  );
  const plan = { ...GH_PLAN, fields: [{ name: 'question_1', label: 'Authorized to work', type: 'single_select', value: 1, option_label: 'Yes' }], for_user: [] };
  const result = await fillPage(page, plan, {}, null);
  assert.equal(await page.$eval('#q1', (el) => el.dataset.picked), 'Yes');
  assert.deepEqual(result.unfilled, []);
  await page.close();
});

test('a dropdown that takes more than 2 s to click is still filled (#137, Browserbase)', async () => {
  // A cover over the dropdown for 3 s stands in for a remote browser, where one click took ~2.5 s.
  const page = await open(`<form><label for="q1">Authorized to work</label>
    <input id="q1" name="question_1" role="combobox" aria-controls="m1" onclick="document.getElementById('m1').hidden = false">
    <ul id="m1" hidden><li role="option" onclick="document.getElementById('q1').dataset.picked = this.textContent">Yes</li></ul>
    <div id="cover" style="position:fixed;inset:0"></div></form>
    <script>setTimeout(() => document.getElementById('cover').remove(), 3000);</script>`);
  const plan = { ...GH_PLAN, fields: [{ name: 'question_1', label: 'Authorized to work', type: 'single_select', value: 1, option_label: 'Yes' }], for_user: [] };
  const result = await fillPage(page, plan, {}, null);
  assert.equal(await page.$eval('#q1', (el) => el.dataset.picked), 'Yes');
  assert.deepEqual(result.unfilled, []);
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

test('isConfirmation: a confirmation URL counts; confirmation text only once the form is gone', () => {
  assert.equal(isConfirmation('greenhouse', 'https://job-boards.greenhouse.io/acme/jobs/1/confirmation', '', true), true);
  assert.equal(isConfirmation('greenhouse', 'https://job-boards.greenhouse.io/acme/jobs/1', 'Apply for this job', true), false);
  assert.equal(isConfirmation('lever', 'https://jobs.lever.co/acme/abc/thanks', '', true), true);
  // A form or posting page can say "thanks for applying" itself.
  assert.equal(isConfirmation('ashby', 'https://jobs.ashbyhq.com/a/1/application', 'Thanks for applying', true), false);
  assert.equal(isConfirmation('ashby', 'https://jobs.ashbyhq.com/a/1/application', 'Thanks for applying', false), true);
  assert.equal(isConfirmation('workday', 'https://x/thanks', 'thanks for applying', false), false); // unsupported platform
});

// Review of PR #130: profile values must never go into an employer's own questions.
test('profile values stay out of textareas, custom questions, and long or question labels', async () => {
  const page = await open(`<form>
    <label for="e">Email</label><input id="e" type="email" name="email">
    <label for="w">Tell us about your website</label><textarea id="w" name="why"></textarea>
    <label for="q">Office location</label><input id="q" name="question_9">
    <label for="c">Phone</label><input id="c" name="cards[abc][field0]">
    <label for="o">Which office location would you prefer</label><input id="o" name="uuid-1">
    <label for="p">Phone?</label><input id="p" name="uuid-2">
    <label for="ph">Phone number</label><input id="ph" name="uuid-3">
    <input id="al" name="uuid-4" aria-label="Which office location would you prefer?">
    <input id="pl" name="uuid-5" placeholder="Your city if different from where you would like to work">
    <button type="submit">Submit</button></form>`);
  await fillPage(page, null, PROFILE, null);
  // A question carried only by aria-label or placeholder is judged the same way as one with a <label>.
  for (const id of ['#w', '#q', '#c', '#o', '#p', '#al', '#pl']) assert.equal(await page.inputValue(id), '', id);
  assert.equal(await page.inputValue('#ph'), '+44 7000 000000'); // short, not a question, UUID-named (Ashby)
  assert.equal(await page.inputValue('#e'), 'jane@example.com');
  await page.close();
});

test('a dropdown picks its own option even when a native select earlier on the page has the same text', async () => {
  const page = await open(`<form>
    <label for="eeo">Are you a veteran</label><select id="eeo"><option></option><option>Yes</option><option>No</option></select>
    <label for="q1">Authorized to work</label><input id="q1" name="question_1" role="combobox" aria-controls="m1">
    <ul id="m1" hidden><li role="option">Yes</li><li role="option">No</li></ul>
    <button type="submit">Submit</button></form>
    <script>
      const q1 = document.getElementById('q1'), m1 = document.getElementById('m1');
      q1.addEventListener('click', () => (m1.hidden = false));
      m1.addEventListener('click', (e) => { q1.value = e.target.textContent; m1.hidden = true; });
    </script>`);
  const plan = { ...GH_PLAN, fields: [{ name: 'question_1', label: 'Authorized to work', type: 'single_select', value: 1, option_label: 'Yes' }] };
  const result = await fillPage(page, plan, PROFILE, null);
  assert.equal(await page.inputValue('#q1'), 'Yes');
  assert.equal(await page.inputValue('#eeo'), ''); // the native select is not touched
  assert.ok(!result.unfilled.includes('Authorized to work'));
  await page.close();
});

test('fields re-rendered after the CV upload are found again and filled', async () => {
  const page = await open(`<form>
    <label for="r">Resume</label><input id="r" type="file" name="resume">
    <div id="box"><label for="n">Full name</label><input id="n" name="name"></div>
    <button type="submit">Submit</button></form>
    <script>
      document.getElementById('r').addEventListener('change', () => {
        document.getElementById('box').innerHTML = '<label for="n">Full name</label><input id="n" name="name">';
      });
    </script>`);
  const result = await fillPage(page, null, PROFILE, CV);
  assert.equal(await page.inputValue('#n'), 'Jane Q Doe');
  assert.deepEqual(result.unfilled, []);
  await page.close();
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

test('saved Databricks form: required fields outside the question API are listed for the user, each once (#137)', async () => {
  const page = await open(readFileSync(new URL('greenhouse-6.html', FIXTURES), 'utf8'));
  const result = await fillPage(page, null, PROFILE, CV);
  for (const label of ['Country', 'School', 'Degree', 'End date month', 'End date year', 'Are you legally authorized to work in the country in which you are applying?']) {
    assert.ok(result.required.includes(label), `${label} not listed: ${result.required.join(' | ')}`);
  }
  assert.ok(result.required.some((l) => l.startsWith('Please confirm whether any of the below applies to you.'))); // checkbox group, by legend
  for (const label of ['First Name', 'Last Name', 'Email', 'Phone']) assert.ok(!result.required.includes(label), `${label} was filled`);
  assert.equal(new Set(result.required).size, result.required.length);
  await page.close();
});

test('required-field check: chosen dropdowns, ticked groups and hidden inputs are not listed; empty ones are (#137)', async () => {
  const page = await open(`<form>
    <label for="a">Picked</label><input id="a" role="combobox" aria-required="true" aria-describedby="a-live">
    <label for="b">Not picked</label><input id="b" role="combobox" aria-required="true" aria-describedby="b-placeholder"><div id="b-placeholder">Select...</div>
    <input required aria-hidden="true" style="opacity:0">
    <label for="c">Hidden</label><input id="c" required style="display:none">
    <fieldset aria-required="true"><legend>Languages *</legend>
      <input type="checkbox" id="l1" name="langs[]" value="1"><label for="l1">English</label>
      <input type="checkbox" id="l2" name="langs[]" value="2"><label for="l2">French</label></fieldset>
    <fieldset aria-required="true"><legend>Ticked</legend><input type="checkbox" name="t[]" checked></fieldset>
    <label for="d">Optional</label><input id="d">
  </form>`);
  const result = await fillPage(page, null, {}, null);
  assert.deepEqual(result.required, ['Not picked', 'Languages']);
  await page.close();
});

test('a planned multi-select answer ticks its own box of the group and never unticks another (#137)', async () => {
  const group = (checked) => `<form><fieldset><legend>Select all that apply</legend>
    <input type="checkbox" id="o1" name="question_9[]" value="11" ${checked}><label for="o1">Citizen of Cuba</label>
    <input type="checkbox" id="o2" name="question_9[]" value="22"><label for="o2">None of the above</label></fieldset></form>`;
  const field = (value) => ({ ...GH_PLAN, fields: [{ name: 'question_9[]', label: 'Select all that apply', type: 'multi_select', value }], for_user: [] });
  let page = await open(group(''));
  let result = await fillPage(page, field(22), {}, null);
  assert.deepEqual([await page.isChecked('#o1'), await page.isChecked('#o2')], [false, true]);
  assert.equal(result.filled, 1);
  await page.close();

  page = await open(group('checked'));
  result = await fillPage(page, field(99), {}, null); // not an option on the live form
  assert.deepEqual([await page.isChecked('#o1'), await page.isChecked('#o2')], [true, false]);
  assert.deepEqual(result.unfilled, ['Select all that apply']);
  await page.close();
});

test('the submit trap itself catches a click on Submit', async () => {
  const page = await open(GREENHOUSE);
  await page.click('button');
  assert.equal(await page.evaluate(() => window.__submitted), true);
  await page.close();
});
