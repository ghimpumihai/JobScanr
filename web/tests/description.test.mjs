// The role panel's live description (#141): employer HTML becomes plain text blocks, and only fixed public hosts are
// called. A fake fetch records every request; nothing goes to the network.
import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { createServer } from 'vite';

const vite = await createServer({ server: { middlewareMode: true, ws: false }, logLevel: 'error' });
after(() => vite.close());
const { htmlToBlocks, fetchDescription } = await vite.ssrLoadModule('/src/lib/server/description.ts');

function fakeFetch(body, status = 200) {
  const calls = [];
  const fn = async (url, init = {}) => {
    calls.push({ url, init });
    return new Response(JSON.stringify(body), { status });
  };
  fn.calls = calls;
  return fn;
}

test('HTML becomes headings, paragraphs and lists of plain text; scripts and markup are dropped', () => {
  const blocks = htmlToBlocks(
    '<div><p>Join&nbsp;us &amp; <b>build</b> things.</p><h3>What you will do</h3><ul><li>Ship <a href="x">code</a></li><li>Review</li></ul>' +
      '<script>alert(1)</script><style>p{}</style><p><strong>Requirements:</strong></p><p>&#60;img onerror=x&#62; &#x2014; ok</p></div>'
  );
  assert.deepEqual(blocks, [
    { p: 'Join us & build things.' },
    { h: 'What you will do' },
    { li: ['Ship code', 'Review'] },
    { h: 'Requirements' },
    { p: '<img onerror=x> — ok' } // stays text: the page renders blocks as text, never as HTML
  ]);
});

test('Greenhouse: the escaped content is decoded once and read from the public board API', async () => {
  const f = fakeFetch({ content: '&lt;p&gt;Hello &amp;amp; welcome&lt;/p&gt;', updated_at: '2026-11-20T10:00:00Z' });
  const d = await fetchDescription('greenhouse', 'acme', '123', f);
  assert.equal(f.calls[0].url, 'https://boards-api.greenhouse.io/v1/boards/acme/jobs/123');
  assert.equal(f.calls[0].init.redirect, 'error');
  assert.deepEqual(d.blocks, [{ p: 'Hello & welcome' }]);
  assert.deepEqual(d.facts, [{ k: 'Updated', v: '20 Nov 2026' }]);
});

test('Lever: description, lists and facts', async () => {
  const f = fakeFetch({
    description: '<div>Intro</div>',
    lists: [{ text: 'You will', content: '<li>Build</li><li>Test</li>' }],
    categories: { commitment: 'Full-time' },
    workplaceType: 'hybrid',
    createdAt: Date.UTC(2026, 10, 3)
  });
  const d = await fetchDescription('lever', 'acme', '0f1e2d3c-aaaa-bbbb-cccc-1234567890ab', f);
  assert.equal(f.calls[0].url, 'https://api.lever.co/v0/postings/acme/0f1e2d3c-aaaa-bbbb-cccc-1234567890ab');
  assert.deepEqual(d.blocks, [{ p: 'Intro' }, { h: 'You will' }, { li: ['Build', 'Test'] }]);
  assert.deepEqual(d.facts, [
    { k: 'Type', v: 'Full-time' },
    { k: 'Workplace', v: 'Hybrid' },
    { k: 'Posted', v: '3 Nov 2026' }
  ]);
});

test('Ashby: the scraper\'s GraphQL query; a null payload (throttling) is a failure, not an empty description', async () => {
  const f = fakeFetch({ data: { jobPosting: { descriptionHtml: '<p>Hi</p>' } } });
  const d = await fetchDescription('ashby', 'acme', 'abc-123', f);
  assert.equal(f.calls[0].url, 'https://jobs.ashbyhq.com/api/non-user-graphql');
  assert.equal(JSON.parse(f.calls[0].init.body).variables.jobPostingId, 'abc-123');
  assert.deepEqual(d.blocks, [{ p: 'Hi' }]);
  await assert.rejects(fetchDescription('ashby', 'acme', 'abc-123', fakeFetch({ data: { jobPosting: null } })));
});

test('Workday: tenant|wdN|site builds the pod host; malformed identifiers call nothing', async () => {
  const f = fakeFetch({ jobPostingInfo: { jobDescription: '<p>Role</p>', timeType: 'Full time' } });
  const d = await fetchDescription('workday', 'acme|wd5|Careers', 'Engineer_R123', f);
  assert.equal(f.calls[0].url, 'https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Careers/job/Engineer_R123');
  assert.deepEqual(d.facts, [{ k: 'Type', v: 'Full time' }]);
  for (const ident of ['evil.com/x|wd5|Careers', 'acme|wdx|Careers', 'acme|wd5', 'acme|wd5|a/b']) {
    const g = fakeFetch({});
    assert.equal(await fetchDescription('workday', ident, 'R1', g), null, ident);
    assert.equal(g.calls.length, 0, ident);
  }
});

test('identifiers that could change the host or path, and platforms without an endpoint, call nothing', async () => {
  for (const [platform, ident, id] of [
    ['greenhouse', 'acme', '12/../../x'],
    ['greenhouse', 'evil.com#', '1'],
    ['lever', 'a/b', 'x'],
    ['smartrecruiters', 'acme', 'x?y'],
    ['teamtailor', 'acme', '1'],
    ['google', 'x', '1']
  ]) {
    const f = fakeFetch({});
    assert.equal(await fetchDescription(platform, ident, id, f), null, `${platform} ${ident} ${id}`);
    assert.equal(f.calls.length, 0);
  }
});

test('an HTTP error is a failure the panel shows as "couldn\'t load"', async () => {
  await assert.rejects(fetchDescription('greenhouse', 'acme', '1', fakeFetch({}, 404)));
});
