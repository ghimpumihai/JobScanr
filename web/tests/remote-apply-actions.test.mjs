// Remote fill sessions (#129) against a fake Supabase, a fake provider and a fake browser. No network.
import assert from 'node:assert/strict';
import { after, beforeEach, test } from 'node:test';
import { createServer } from 'vite';

process.env.SUPABASE_URL = 'https://x.supabase.co';
process.env.SUPABASE_ANON_KEY = 'test-anon-key';
const logged = [];
console.error = (...args) => logged.push(args.join(' '));

const vite = await createServer({ server: { middlewareMode: true, ws: false }, logLevel: 'error' });
after(() => vite.close());
const session = await vite.ssrLoadModule('/src/lib/server/remoteApply/session.ts');
const { actions } = await vite.ssrLoadModule('/src/routes/(app)/applications/+page.server.ts');
const { startSession, checkSession, formUrl, deps, DAILY_CAP } = session;

const NOW = new Date('2026-11-24T10:00:00Z');
const USER = {
  id: 7,
  email: 'jane@example.com',
  resume_storage_path: 'uid-1/8f3a2c.pdf',
  resume_filename: 'Jane Doe CV.pdf',
  screening_defaults: { full_name: 'Jane Doe' },
  resume_data: { phone: '+44 1', location: 'London', urls: { linkedin: 'https://linkedin.com/in/j' } }
};
const APP = {
  id: 55,
  status: 'manual_apply',
  job_postings: {
    url: 'https://boards.greenhouse.io/acme/jobs/1',
    external_id: '1',
    companies: { ats_platform: 'greenhouse', ats_identifier: 'acme' }
  }
};
const PLAN = {
  version: 1,
  platform: 'greenhouse',
  posting_url: 'https://job-boards.greenhouse.io/embed/job_app?for=acme&token=1',
  fields: [],
  for_user: [{ name: 'question_4', label: 'Why Acme?', reason: 'open_ended' }]
};

/** Records every query; answers per table and operation. */
function fakeSb({ user = USER, app = APP, count = 0, plan = PLAN, cv = Buffer.from('%PDF'), insertError = null, row = null, saveError = null, markError = null, stale = [] } = {}) {
  const log = [];
  const answer = (q) => {
    if (q.table === 'users') return { data: user, error: user ? null : { message: 'x' } };
    if (q.table === 'applications') {
      if (q.op !== 'update') return { data: app };
      return markError ? { data: null, error: markError } : { data: [{ id: app?.id }] };
    }
    if (q.table === 'application_fill_plans') return { data: plan ? { plan } : null };
    if (q.table === 'remote_apply_sessions') {
      if (q.op === 'insert') return insertError ? { data: null, error: insertError } : { data: { id: 900 } };
      if (q.op === 'update' && q.filters.some(([k]) => k === '<started_at')) return { data: stale, error: null };
      if (q.op === 'update') return { data: null, error: saveError && 'provider_session_id' in q.values ? saveError : null };
      if (q.opts?.head) return { count, error: null };
      return { data: row };
    }
    throw new Error(`unexpected table ${q.table}`);
  };
  const sb = {
    log,
    from(table) {
      const q = { table, op: 'select', filters: [], values: null, opts: null };
      const done = () => (log.push(q), Promise.resolve(answer(q)));
      const b = {
        select(cols, opts) {
          if (q.op === 'select') q.opts = opts ?? null;
          return b;
        },
        insert(v) {
          q.op = 'insert';
          q.values = v;
          return b;
        },
        update(v) {
          q.op = 'update';
          q.values = v;
          return b;
        },
        eq(k, v) {
          q.filters.push([k, v]);
          return b;
        },
        gte(k, v) {
          q.filters.push([`>=${k}`, v]);
          return b;
        },
        lt(k, v) {
          q.filters.push([`<${k}`, v]);
          return b;
        },
        single: done,
        maybeSingle: done,
        then: (res, rej) => done().then(res, rej)
      };
      return b;
    },
    storage: {
      from: () => ({
        download: async (path) => (cv ? { data: new Blob([cv], { type: 'application/pdf' }), error: null, path } : { data: null, error: { message: 'x' } })
      })
    }
  };
  return sb;
}

let world;
function fakeWorld({ gotoStatus = 200, pageUrl = 'https://job-boards.greenhouse.io/embed/job_app?for=acme&token=1', body = 'Apply for this job', running = true, connectError = null, createError = null, captcha = false, fileInputs = 1, lookupError = null, liveViewErrors = [] } = {}) {
  const w = { calls: [], released: [], filled: null, closed: 0, providersAsked: [], liveViewCalls: 0 };
  const CONNECTION = { url: 'wss://connect.example/', headers: { Authorization: 'Bearer SECRET' } };
  const page = {
    goto: async (url) => (w.calls.push(['goto', url]), { status: () => gotoStatus }),
    url: () => pageUrl,
    locator: () => ({ first: () => ({ waitFor: async () => {} }), innerText: async () => body, count: async () => fileInputs })
  };
  const browser = { contexts: () => [{ pages: () => [page], newPage: async () => page }], close: async () => void w.closed++ };
  deps.provider = (name) => (w.providersAsked.push(name), {
    name: 'fake',
    create: async () => {
      if (createError) throw createError;
      w.calls.push(['create']);
      return { id: 'bb-1', connection: CONNECTION };
    },
    connection: async () => {
      if (lookupError) throw lookupError;
      return running ? CONNECTION : null;
    },
    liveViewUrl: async () => {
      w.closedAtLiveView = w.closed;
      const failure = liveViewErrors[w.liveViewCalls++]; // one entry per failing call, in order
      if (failure) throw failure;
      return 'https://live.example/view?token=LIVE';
    },
    release: async (id) => void w.released.push(id),
    listRunning: async () => []
  });
  deps.connect = async (connection) => {
    if (connectError) throw connectError;
    w.calls.push(['connect', connection]);
    return browser;
  };
  deps.fill = async (_page, plan, profile, cv) => {
    w.filled = { plan, profile, cv };
    return { planned: 6, filled: 5, unfilled: ['location'], cvAttached: true };
  };
  deps.captchaVisible = async () => captcha;
  deps.now = () => new Date(NOW);
  return w;
}

beforeEach(() => {
  process.env.REMOTE_APPLY_ENABLED = 'true';
  process.env.REMOTE_APPLY_USER_IDS = '3, 7';
  logged.length = 0;
  world = fakeWorld();
});

const updates = (sb, table = 'remote_apply_sessions') => sb.log.filter((q) => q.table === table && q.op === 'update');

test('start: fills the bare Greenhouse form in a new session and returns the live view', async () => {
  const sb = fakeSb();
  const result = await startSession(sb, 'uid-1', 55);

  assert.deepEqual(result, { sessionId: 900, liveViewUrl: 'https://live.example/view?token=LIVE', leftForUser: ['Why Acme?', 'location'] });
  const insert = sb.log.find((q) => q.op === 'insert');
  assert.deepEqual(insert.values, { application_id: 55, user_id: 7, provider: 'fake' });
  assert.deepEqual(world.calls.find((c) => c[0] === 'goto'), ['goto', PLAN.posting_url]);
  assert.equal(world.filled.profile.full_name, 'Jane Doe');
  assert.equal(world.filled.profile.linkedin, 'https://linkedin.com/in/j');
  assert.equal(world.filled.cv.name, 'Jane Doe CV.pdf'); // the uploaded name, not the storage object's
  assert.equal(world.closedAtLiveView, 1); // disconnected before the live view: Cloudflare opens its own
  assert.equal(world.filled.cv.buffer.toString(), '%PDF');
  const [stale, ...rest] = updates(sb);
  // Open rows of this application past the 15-minute limit are expired first, so they cannot block it.
  assert.deepEqual(stale.values, { status: 'expired', ended_at: NOW.toISOString() });
  assert.deepEqual(stale.filters, [['application_id', 55], ['status', 'open'], ['<started_at', '2026-11-24T09:45:00.000Z']]);
  assert.ok(sb.log.indexOf(stale) < sb.log.findIndex((q) => q.op === 'insert'));
  assert.deepEqual(rest.map((q) => q.values), [
    { provider_session_id: 'bb-1' },
    { fields_planned: 6, fields_filled: 5, fields_unfilled: 1, captcha_seen: false }
  ]);
  assert.equal(world.closed, 1); // disconnected; the session stays up for the live view
  assert.deepEqual(world.released, []);
  // The live view URL and the connect key are never written to the database.
  assert.ok(!JSON.stringify(sb.log).includes('LIVE') && !JSON.stringify(sb.log).includes('SECRET'));
});

const refusals = [
  ['the switch is off', () => (process.env.REMOTE_APPLY_ENABLED = 'false'), {}, 503],
  ['the user is not in the trial', () => (process.env.REMOTE_APPLY_USER_IDS = '3'), {}, 403],
  ['the application is not To Apply', null, { app: { ...APP, status: 'submitted' } }, 409],
  ['the platform is Workday', null, { app: { ...APP, job_postings: { ...APP.job_postings, companies: { ats_platform: 'workday' } } } }, 422],
  ['the daily cap is used', null, { count: 5 }, 429],
  ['there is no CV', null, { user: { ...USER, resume_storage_path: null } }, 422],
  ['the CV is over 2 MB', null, { cv: Buffer.alloc(2 * 1024 * 1024 + 1) }, 422],
  ['a session is already open', null, { insertError: { code: '23505', message: 'dup' } }, 409]
];
for (const [name, setup, opts, status] of refusals) {
  test(`start refuses when ${name}, before any browser`, async () => {
    setup?.();
    await assert.rejects(startSession(fakeSb(opts), 'uid-1', 55), (e) => e.status === status);
    assert.equal(world.calls.length, 0);
  });
}

test('start: the daily cap counts this user since midnight UTC', async () => {
  const sb = fakeSb({ count: DAILY_CAP - 1 });
  await startSession(sb, 'uid-1', 55);
  const countQuery = sb.log.find((q) => q.opts?.head);
  assert.deepEqual(countQuery.filters, [['user_id', 7], ['>=started_at', '2026-11-24T00:00:00.000Z']]);
});

test('start: a closed posting marks the session posting_gone and releases it', async () => {
  world = fakeWorld({ gotoStatus: 404 });
  const sb = fakeSb();
  await assert.rejects(startSession(sb, 'uid-1', 55), (e) => e.status === 410);
  assert.deepEqual(world.released, ['bb-1']);
  assert.equal(updates(sb).at(-1).values.status, 'posting_gone');
});

test('start: a browser failure releases the session, records the error name only, and never logs the key', async () => {
  world = fakeWorld({ connectError: new TypeError('connect wss://connect.example/ with Bearer SECRET failed') });
  const sb = fakeSb();
  await assert.rejects(startSession(sb, 'uid-1', 55), (e) => e.status === 502);
  assert.deepEqual(world.released, ['bb-1']);
  assert.deepEqual(updates(sb).at(-1).values, { status: 'error', ended_at: NOW.toISOString(), error: 'TypeError' });
  assert.ok(!logged.join('\n').includes('SECRET'));
});

test('start: if the provider session id cannot be saved, the session is released, not orphaned', async () => {
  const sb = fakeSb({ saveError: { message: 'x' } });
  await assert.rejects(startSession(sb, 'uid-1', 55), (e) => e.status === 502);
  assert.deepEqual(world.released, ['bb-1']);
  assert.equal(world.calls.filter((c) => c[0] === 'connect').length, 0); // stopped before filling anything
  assert.equal(updates(sb).at(-1).values.status, 'error');
});

test('start: one failed live view request is retried; two 429s end in the quota message', async () => {
  world = fakeWorld({ liveViewErrors: [new Error('blip')] });
  const ok = await startSession(fakeSb(), 'uid-1', 55);
  assert.equal(ok.liveViewUrl, 'https://live.example/view?token=LIVE');
  assert.equal(world.liveViewCalls, 2);
  assert.deepEqual(world.released, []);

  const quota = Object.assign(new Error('Cloudflare Browser Run returned 429'), { status: 429 });
  world = fakeWorld({ liveViewErrors: [quota, quota] });
  const sb = fakeSb();
  await assert.rejects(startSession(sb, 'uid-1', 55), (e) => e.status === 503 && /no free time left/.test(e.message));
  assert.equal(updates(sb).at(-1).values.error, 'quota');
  assert.deepEqual(world.released, ['bb-1']);
});

test('start: stale open rows of the application are expired and their browsers released', async () => {
  const sb = fakeSb({ stale: [{ provider: 'cloudflare', provider_session_id: 'old-1' }, { provider: 'browserbase', provider_session_id: null }] });
  await startSession(sb, 'uid-1', 55);
  assert.deepEqual(world.released, ['old-1']); // the one with a provider session; the new session stays up
  assert.ok(world.providersAsked.includes('cloudflare')); // released through the provider that made it
});

test('formUrl: only the ATS-hosted form page', () => {
  assert.equal(formUrl('lever', { url: 'https://jobs.lever.co/acme/abc' }, null), 'https://jobs.lever.co/acme/abc/apply');
  assert.equal(formUrl('lever', { url: 'https://jobs.lever.co/acme/abc/apply' }, null), 'https://jobs.lever.co/acme/abc/apply');
  assert.equal(formUrl('ashby', { url: 'https://jobs.ashbyhq.com/acme/abc?src=x' }, null), 'https://jobs.ashbyhq.com/acme/abc/application');
  assert.equal(
    formUrl('greenhouse', { url: 'https://acme.com/careers?gh_jid=1', external_id: '1', ats_identifier: 'acme' }, null),
    'https://job-boards.greenhouse.io/embed/job_app?for=acme&token=1'
  );
  assert.equal(formUrl('lever', { url: 'https://evil.example/acme/abc' }, null), null);
  assert.equal(formUrl('lever', { url: 'javascript:alert(1)' }, null), null);
  assert.equal(formUrl('greenhouse', {}, { ...PLAN, posting_url: 'http://job-boards.greenhouse.io/x' }), null); // https only
});

const OPEN_ROW = {
  id: 900,
  status: 'open',
  provider: 'cloudflare',
  provider_session_id: 'bb-1',
  captcha_seen: false,
  started_at: '2026-11-24T09:55:00Z',
  application_id: 55,
  applications: { job_postings: { companies: { ats_platform: 'greenhouse' } } }
};

test('check: the confirmation page records Applied with the Mark as Applied update, then closes', async () => {
  world = fakeWorld({ pageUrl: 'https://job-boards.greenhouse.io/embed/job_app/confirmation', body: 'Thank you for applying.' });
  const sb = fakeSb({ row: OPEN_ROW });
  assert.deepEqual(await checkSession(sb, 900), { state: 'submitted' });
  const appUpdate = updates(sb, 'applications')[0];
  assert.deepEqual(appUpdate.values, { status: 'submitted' });
  assert.deepEqual(appUpdate.filters, [['id', 55], ['status', 'manual_apply']]);
  const closed = updates(sb).at(-1);
  assert.equal(closed.values.status, 'submitted');
  assert.deepEqual(closed.filters, [['id', 900], ['status', 'open']]);
  assert.deepEqual(world.released, ['bb-1']);
});

test('check: uses the provider that made the session, not the one configured now', async () => {
  process.env.REMOTE_APPLY_PROVIDER = 'browserbase';
  await checkSession(fakeSb({ row: OPEN_ROW }), 900);
  assert.deepEqual(world.providersAsked, ['cloudflare']);
  delete process.env.REMOTE_APPLY_PROVIDER;
});

test('start: a provider out of free minutes (429) says so, records quota, and opens nothing', async () => {
  world = fakeWorld({ createError: Object.assign(new Error('Cloudflare Browser Run returned 429'), { status: 429 }) });
  const sb = fakeSb();
  await assert.rejects(startSession(sb, 'uid-1', 55), (e) => e.status === 503 && /no free time left/.test(e.message));
  assert.equal(updates(sb).at(-1).values.error, 'quota');
  assert.equal(world.calls.length, 0);
});

test('check: confirmation text counts only once the form (its CV upload) is gone', async () => {
  const ashbyRow = { ...OPEN_ROW, applications: { job_postings: { companies: { ats_platform: 'ashby' } } } };
  world = fakeWorld({ pageUrl: 'https://jobs.ashbyhq.com/acme/1/application', body: 'Thanks for applying! Questions?', fileInputs: 1 });
  let sb = fakeSb({ row: ashbyRow });
  assert.deepEqual(await checkSession(sb, 900), { state: 'open', captcha: false });
  assert.equal(updates(sb, 'applications').length, 0);
  world = fakeWorld({ pageUrl: 'https://jobs.ashbyhq.com/acme/1/application', body: 'Thanks for applying!', fileInputs: 0 });
  sb = fakeSb({ row: ashbyRow });
  assert.deepEqual(await checkSession(sb, 900), { state: 'submitted' });
});

test('check: if marking Applied fails, the user is told to mark it themselves', async () => {
  world = fakeWorld({ pageUrl: 'https://job-boards.greenhouse.io/embed/job_app/confirmation', body: 'Thank you for applying.', fileInputs: 0 });
  const sb = fakeSb({ row: OPEN_ROW, markError: { message: 'x' } });
  assert.deepEqual(await checkSession(sb, 900), { state: 'unrecorded' });
  assert.equal(updates(sb).at(-1).values.status, 'submitted'); // the session itself did end with a confirmation
});

test('check: a failed session lookup (a 429, a blip) keeps the session open; on close it is abandoned', async () => {
  world = fakeWorld({ lookupError: Object.assign(new Error('Cloudflare Browser Run returned 429'), { status: 429 }) });
  const sb = fakeSb({ row: OPEN_ROW });
  assert.deepEqual(await checkSession(sb, 900), { state: 'open' });
  assert.deepEqual(world.released, []); // the live view keeps running
  assert.equal(updates(sb).length, 0);
  assert.deepEqual(await checkSession(fakeSb({ row: OPEN_ROW }), 900, true), { state: 'abandoned' });
});

test('check: a confirmation found as the session expires or the switch goes off is still recorded', async () => {
  const confirmed = { pageUrl: 'https://job-boards.greenhouse.io/embed/job_app/confirmation', body: 'Thank you for applying.', fileInputs: 0 };
  world = fakeWorld(confirmed);
  let sb = fakeSb({ row: { ...OPEN_ROW, started_at: '2026-11-24T09:40:00Z' } }); // 20 minutes old
  assert.deepEqual(await checkSession(sb, 900), { state: 'submitted' });
  assert.equal(updates(sb, 'applications').length, 1);

  process.env.REMOTE_APPLY_ENABLED = 'false';
  world = fakeWorld(confirmed);
  sb = fakeSb({ row: OPEN_ROW });
  assert.deepEqual(await checkSession(sb, 900), { state: 'submitted' });
  process.env.REMOTE_APPLY_ENABLED = 'true';
});

test('check: still filling stays open and records a captcha once seen', async () => {
  world = fakeWorld({ captcha: true });
  const sb = fakeSb({ row: OPEN_ROW });
  assert.deepEqual(await checkSession(sb, 900), { state: 'open', captcha: true });
  assert.deepEqual(updates(sb).map((q) => q.values), [{ captcha_seen: true }]);
  assert.equal(updates(sb, 'applications').length, 0);
  assert.deepEqual(world.released, []);
});

test('check: closing the view without a confirmation is abandoned, never Applied', async () => {
  const sb = fakeSb({ row: OPEN_ROW });
  assert.deepEqual(await checkSession(sb, 900, true), { state: 'abandoned' });
  assert.equal(updates(sb, 'applications').length, 0);
  assert.deepEqual(world.released, ['bb-1']);
});

test('check: switch off, too old, or provider gone all expire the session', async () => {
  process.env.REMOTE_APPLY_ENABLED = 'false';
  assert.deepEqual(await checkSession(fakeSb({ row: OPEN_ROW }), 900), { state: 'expired' });
  process.env.REMOTE_APPLY_ENABLED = 'true';
  assert.deepEqual(await checkSession(fakeSb({ row: { ...OPEN_ROW, started_at: '2026-11-24T09:40:00Z' } }), 900), { state: 'expired' });
  world = fakeWorld({ running: false });
  assert.deepEqual(await checkSession(fakeSb({ row: OPEN_ROW }), 900), { state: 'expired' });
});

test('check: a finished session is reported as is, without touching the provider', async () => {
  const sb = fakeSb({ row: { ...OPEN_ROW, status: 'submitted' } });
  assert.deepEqual(await checkSession(sb, 900), { state: 'submitted' });
  assert.equal(world.calls.length, 0);
  assert.equal(updates(sb).length, 0);
});

function form(fields) {
  const body = new FormData();
  for (const [k, v] of Object.entries(fields)) body.set(k, v);
  return new Request('http://localhost/applications', { method: 'POST', body });
}

test('actions refuse a bad id and demo mode', async () => {
  const locals = { user: null, supabase: null };
  for (const name of ['remoteStart', 'remotePoll', 'remoteEnd']) {
    assert.equal((await actions[name]({ request: form({ id: 'x' }), locals })).status, 400);
    const demo = await actions[name]({ request: form({ id: '5' }), locals });
    assert.equal(demo.status, 400);
    assert.match(demo.data.error, /demo/);
  }
});
