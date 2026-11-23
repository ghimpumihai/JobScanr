// Runs the real /applications load and setStatus action against a fake Supabase client that records every query.
// The fake does not filter rows, so these tests prove which filters are sent; staging proves PostgREST applies them.
import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { createServer } from 'vite';

process.env.SUPABASE_URL = 'https://x.supabase.co';
process.env.SUPABASE_ANON_KEY = 'test-anon-key';
console.error = () => {}; // the module logs every failure these tests provoke

const vite = await createServer({ server: { middlewareMode: true, ws: false }, logLevel: 'error' });
after(() => vite.close());
const { actions, load } = await vite.ssrLoadModule('/src/routes/(app)/applications/+page.server.ts');

const UID = '11111111-1111-1111-1111-111111111111';
const PROFILE_ROW = {
  email: 'jane@example.com',
  resume_filename: 'Jane CV.pdf',
  screening_defaults: { full_name: 'Jane Doe' },
  resume_data: { phone: '+44 1', location: 'London', urls: { linkedin: 'https://linkedin.com/in/j' } }
};
const ROW = {
  id: 7,
  status: 'manual_apply',
  created_at: '2026-11-20T08:00:00Z',
  applied_at: null,
  job_postings: {
    title: 'Junior Engineer',
    location: 'London',
    url: 'https://boards.greenhouse.io/acme/jobs/1',
    last_seen_at: '2026-11-22T06:00:00Z',
    companies: { name: 'Acme', ats_platform: 'greenhouse' }
  }
};

/** status: the stored row's status, for compare-and-set updates. fail: { rows, count, profile, update }. */
function world({ rows = [ROW], counts = {}, profile = PROFILE_ROW, status = 'manual_apply', fail = {} } = {}) {
  const w = { queries: [], status };
  function from(table) {
    const ops = [];
    w.queries.push({ table, ops });
    const respond = () => {
      const has = (name) => ops.find((op) => op[0] === name);
      if (table === 'users') return fail.profile ? { data: null, error: fail.profile } : { data: profile, error: null };
      const update = has('update');
      if (update) {
        if (fail.update) return { data: null, error: fail.update };
        const wanted = ops.find((op) => op[0] === 'eq' && op[1] === 'status')?.[2];
        if (wanted !== w.status) return { data: [], error: null };
        w.status = update[1].status;
        return { data: [{ id: 7 }], error: null };
      }
      if (has('select')[2]?.head) {
        if (fail.count) return { count: null, error: fail.count };
        const s = ops.find((op) => op[0] === 'eq' && op[1] === 'status')[2];
        return { count: counts[s] ?? 0, error: null };
      }
      return fail.rows ? { data: null, error: fail.rows } : { data: rows, error: null };
    };
    const builder = {};
    for (const name of ['select', 'eq', 'ilike', 'gte', 'lt', 'order', 'range', 'update', 'single']) {
      builder[name] = (...args) => (ops.push([name, ...args]), builder);
    }
    builder.then = (resolve, reject) => Promise.resolve(respond()).then(resolve, reject);
    return builder;
  }
  w.locals = { user: { id: UID }, supabase: { from } };
  w.rowQuery = () => w.queries.find((q) => q.table === 'applications' && !q.ops.find((op) => op[0] === 'select')[2]);
  w.countQueries = () => w.queries.filter((q) => q.table === 'applications' && q.ops.find((op) => op[0] === 'select')[2]);
  return w;
}

const loadPage = (w, query = '') => load({ locals: w.locals, url: new URL(`http://localhost/applications${query}`) });
const filters = (q) => q.ops.filter((op) => ['eq', 'ilike', 'gte', 'lt'].includes(op[0]));

function act(w, fields) {
  const body = new FormData();
  for (const [key, value] of Object.entries(fields)) body.append(key, value);
  return actions.setStatus({ locals: w.locals, request: new Request('http://localhost/', { method: 'POST', body }) });
}
const refused = (result, status, message = /./) => {
  assert.equal(result.status, status, JSON.stringify(result));
  assert.match(result.data.error, message);
};

test('load sends the tab, every filter and the page to the database', async () => {
  const w = world();
  const company = encodeURIComponent('50%_off*\\');
  await loadPage(w, `?tab=applied&platform=lever&company=${company}&from=2026-11-01&to=2026-11-30&page=2`);
  const rows = w.rowQuery();
  assert.deepEqual(filters(rows), [
    ['eq', 'status', 'submitted'],
    ['eq', 'job_postings.companies.ats_platform', 'lever'],
    ['ilike', 'job_postings.companies.name', '%50\\%\\_off\\\\%'], // LIKE wildcards escaped, PostgREST's * removed
    ['gte', 'applied_at', '2026-11-01T00:00:00.000Z'], // Applied filters on the day the user marked it
    ['lt', 'applied_at', '2026-12-01T00:00:00.000Z'] // "to" includes its whole day
  ]);
  assert.deepEqual(
    rows.ops.filter((op) => op[0] === 'order' || op[0] === 'range'),
    [
      ['order', 'created_at', { ascending: false }],
      ['order', 'id', { ascending: false }],
      ['range', 50, 99]
    ]
  );
  assert.match(rows.ops[0][1], /job_postings!inner\(.*companies!inner\(/s); // filters on joined columns need inner joins
});

test('every tab is counted with the same filters', async () => {
  const w = world({ counts: { manual_apply: 3, submitted: 2, dismissed: 1, stale_closed: 75 } });
  const page = await loadPage(w, '?platform=workday');
  assert.deepEqual(page.counts, { to_apply: 3, applied: 2, not_interested: 1, closed: 75 });
  for (const q of w.countQueries()) {
    assert.deepEqual(q.ops.find((op) => op[0] === 'select')[2], { count: 'exact', head: true });
    assert.deepEqual(filters(q)[1], ['eq', 'job_postings.companies.ats_platform', 'workday']);
  }
  assert.deepEqual(w.countQueries().map((q) => filters(q)[0][2]).sort(), [
    'dismissed',
    'manual_apply',
    'stale_closed',
    'submitted'
  ]);
});

test('other tabs filter dates on when the application was added', async () => {
  const w = world();
  await loadPage(w, '?tab=closed&from=2026-11-01');
  assert.deepEqual(filters(w.rowQuery()), [
    ['eq', 'status', 'stale_closed'],
    ['gte', 'created_at', '2026-11-01T00:00:00.000Z']
  ]);
});

test('invalid parameters are ignored', async () => {
  for (const query of [
    '?tab=queued&platform=evil&page=0',
    `?company=${'x'.repeat(101)}&from=2026-02-30&to=yesterday&page=-1`,
    '?from=2026-13-01&to=2026-1-1&page=abc',
    '?company=%20%20&page=1.5'
  ]) {
    const w = world();
    await loadPage(w, query);
    assert.deepEqual(filters(w.rowQuery()), [['eq', 'status', 'manual_apply']], query);
    assert.deepEqual(w.rowQuery().ops.at(-1), ['range', 0, 49], query);
  }
});

test('rows are mapped for the page and unsafe posting URLs are not linked', async () => {
  const unsafe = { ...ROW, id: 8, job_postings: { ...ROW.job_postings, url: 'javascript:alert(1)' } };
  const page = await loadPage(world({ rows: [ROW, unsafe] }));
  assert.equal(page.loadError, false);
  assert.deepEqual(page.applications[0], {
    id: 7,
    status: 'manual_apply',
    title: 'Junior Engineer',
    company_name: 'Acme',
    location: 'London',
    ats_platform: 'greenhouse',
    url: 'https://boards.greenhouse.io/acme/jobs/1',
    added_at: '2026-11-20T08:00:00Z',
    applied_at: null,
    last_seen_at: '2026-11-22T06:00:00Z'
  });
  assert.equal(page.applications[1].url, '#');
  assert.equal(page.tab, 'to_apply');
});

test('the drawer gets the saved details, with no invented values', async () => {
  const page = await loadPage(world({ profile: { email: 'a@example.com', screening_defaults: {}, resume_data: {} } }));
  assert.deepEqual(page.profile, {
    full_name: '',
    email: 'a@example.com',
    phone: '',
    location: '',
    linkedin: '',
    github: '',
    portfolio: '',
    resume_filename: ''
  });
  const full = await loadPage(world());
  assert.equal(full.profile.full_name, 'Jane Doe');
  assert.equal(full.profile.linkedin, 'https://linkedin.com/in/j');
  assert.equal(full.profile.resume_filename, 'Jane CV.pdf');
});

test('any failed read is a load error, never demo data', async () => {
  const error = { code: '42501', message: 'denied' };
  for (const fail of [{ rows: error }, { count: error }, { profile: error }]) {
    const page = await loadPage(world({ fail }));
    assert.equal(page.loadError, true, JSON.stringify(fail));
    assert.deepEqual(page.applications, []);
    assert.equal(page.demo, false);
  }
});

test('demo sessions see demo rows and query nothing', async () => {
  const w = world();
  w.locals.user.id = 'demo-user-id';
  const page = await loadPage(w);
  assert.equal(page.demo, true);
  assert.ok(page.applications.length > 0);
  assert.ok(page.applications.every((a) => a.status === 'manual_apply'));
  assert.deepEqual(w.queries, []);
});

test('each allowed change is sent as a compare-and-set update and can be undone', async () => {
  for (const [from, to, undo] of [
    ['manual_apply', 'submitted', 'manual_apply'],
    ['stale_closed', 'submitted', 'manual_apply'],
    ['manual_apply', 'dismissed', 'manual_apply'],
    ['stale_closed', 'dismissed', 'manual_apply'],
    ['dismissed', 'manual_apply', null],
    ['submitted', 'manual_apply', null]
  ]) {
    const w = world({ status: from });
    const result = await act(w, { id: '7', from, to });
    assert.equal(result.success, true, `${from} -> ${to}`);
    const ops = w.queries[0].ops;
    assert.deepEqual(ops.slice(0, 3), [['update', { status: to }], ['eq', 'id', 7], ['eq', 'status', from]]);
    assert.equal(w.status, to);
    assert.deepEqual(result.undo, undo && { id: 7, from: to, to: undo });
  }
});

test('changes the database would refuse are refused first', async () => {
  for (const fields of [
    { id: '7', from: 'manual_apply', to: 'stale_closed' },
    { id: '7', from: 'submitted', to: 'dismissed' },
    { id: '7', from: 'queued', to: 'submitted' },
    { id: 'x', from: 'manual_apply', to: 'submitted' },
    { id: '', from: 'manual_apply', to: 'submitted' },
    { from: 'manual_apply', to: 'submitted' }
  ]) {
    const w = world();
    refused(await act(w, fields), 400);
    assert.deepEqual(w.queries, [], JSON.stringify(fields));
  }
});

test('a row changed elsewhere is reported, not overwritten', async () => {
  const w = world({ status: 'submitted' });
  refused(await act(w, { id: '7', from: 'manual_apply', to: 'dismissed' }), 409, /already changed/);
  assert.equal(w.status, 'submitted');
});

test('database errors give specific messages', async () => {
  const run = (update) => act(world({ fail: { update } }), { id: '7', from: 'manual_apply', to: 'submitted' });
  refused(await run({ code: 'P0001', message: 'This status change is not allowed' }), 400, /not allowed/);
  refused(await run({ code: '', message: 'fetch failed' }), 503, /unknown/);
  refused(await run({ code: '42501', message: 'denied' }), 500);
});

test('demo sessions change nothing', async () => {
  const w = world();
  w.locals.user.id = 'demo-user-id';
  const result = await act(w, { id: '7', from: 'manual_apply', to: 'submitted' });
  assert.equal(result.success, true);
  assert.match(result.message, /Demo/);
  assert.deepEqual(w.queries, []);
});
