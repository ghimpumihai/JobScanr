// Runs the real /settings actions against an in-memory Supabase fake. The fake copies the rules of
// protect_user_worker_fields (db/schema.sql), so it does not prove the SQL itself.
import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { createServer } from 'vite';

process.env.SUPABASE_URL = 'https://x.supabase.co';
process.env.SUPABASE_ANON_KEY = 'test-anon-key';
console.error = () => {}; // the actions log every failure these tests provoke

const vite = await createServer({ server: { middlewareMode: true, ws: false }, logLevel: 'error' });
after(() => vite.close());
const { actions, load } = await vite.ssrLoadModule('/src/routes/(app)/settings/+page.server.ts');

const UID = '11111111-1111-1111-1111-111111111111';
const OLD_PATH = `${UID}/old.pdf`;
const CONFIRMED = {
  resume_storage_path: OLD_PATH,
  resume_filename: 'My CV.pdf',
  resume_uploaded_at: 'T0',
  resume_confirmed_at: 'C0',
  auto_apply_mode: 'auto_submit'
};
const UNCONFIRMED = {
  ...CONFIRMED,
  resume_confirmed_at: null,
  auto_apply_mode: 'approval_required',
  screening_defaults: { full_name: 'Jane Doe', work_authorization: true, requires_sponsorship: false }
};

function applyTrigger(before, next) {
  if (
    next.resume_storage_path !== before.resume_storage_path ||
    next.resume_uploaded_at !== before.resume_uploaded_at
  ) {
    next.resume_confirmed_at = null;
    if (next.auto_apply_mode === 'auto_submit') next.auto_apply_mode = 'approval_required';
  }
  if (next.auto_apply_mode === 'auto_submit' && !(next.resume_storage_path && next.resume_confirmed_at)) {
    return { code: 'P0001', message: 'Confirm your CV before enabling automatic submission' };
  }
  return null;
}

/** fail: { read, upload, remove, sign: true } or { update: error, updateApplied: true if the row still changed }. */
function world(row = {}, fail = {}) {
  const w = {
    objects: new Set(),
    calls: [],
    row: {
      id: 1,
      auth_user_id: UID,
      email: 'jane@example.com',
      screening_defaults: {},
      profile_filters: {},
      resume_data: {},
      auto_apply_mode: 'approval_required',
      max_daily_applications: 10,
      resume_storage_path: null,
      resume_uploaded_at: null,
      resume_confirmed_at: null,
      ...row
    }
  };
  if (w.row.resume_storage_path) w.objects.add(w.row.resume_storage_path);
  const failure = { error: { message: 'injected' }, data: null };

  function query() {
    let patch;
    let single = false;
    const filters = [];
    const run = () => {
      const hit = filters.every(([key, value]) => w.row[key] === value);
      if (!patch) {
        if (fail.read) return failure;
        return hit ? { data: structuredClone(w.row), error: null } : failure;
      }
      w.calls.push(['update', patch]);
      if (fail.update && !fail.updateApplied) return { data: null, error: fail.update };
      if (!hit) return single ? { data: null, error: { code: 'PGRST116', message: '0 rows' } } : { data: [], error: null };
      const next = { ...w.row, ...patch };
      const raised = applyTrigger(w.row, next);
      if (raised) return { data: null, error: raised };
      w.row = next;
      return fail.update ? { data: null, error: fail.update } : { data: single ? { id: 1 } : [{ id: 1 }], error: null };
    };
    const builder = {
      select: () => builder,
      update: (value) => ((patch = value), builder),
      eq: (key, value) => (filters.push([key, value]), builder),
      single: () => ((single = true), builder),
      then: (resolve, reject) => Promise.resolve(run()).then(resolve, reject)
    };
    return builder;
  }

  const bucket = {
    upload: async (path) => {
      w.calls.push(['upload', path]);
      if (fail.upload) return failure;
      w.objects.add(path);
      return { error: null };
    },
    remove: async (paths) => {
      w.calls.push(['remove', ...paths]);
      if (fail.remove) return failure;
      paths.forEach((path) => w.objects.delete(path));
      return { error: null };
    },
    createSignedUrl: async (path, seconds) => {
      w.calls.push(['sign', path, seconds]);
      return fail.sign ? failure : { data: { signedUrl: 'https://x.supabase.co/s?token=T' }, error: null };
    }
  };
  w.locals = { user: { id: UID }, supabase: { from: query, storage: { from: () => bucket } } };
  return w;
}

function run(w, action, fields = {}) {
  const body = new FormData();
  for (const [key, value] of Object.entries(fields)) body.append(key, value);
  return actions[action]({ locals: w.locals, request: new Request('http://localhost/', { method: 'POST', body }) });
}

const pdf = () => new File([new TextEncoder().encode('%PDF-1.4')], 'My CV.pdf');
const ok = (result) => assert.equal(result.success, true, JSON.stringify(result));
function refused(result, status, message = /./) {
  assert.equal(result.status, status, JSON.stringify(result));
  assert.match(result.data.error, message);
}

test('first upload stores one file in the user folder', async () => {
  const w = world();
  ok(await run(w, 'uploadCv', { cv: pdf() }));
  assert.equal(w.objects.size, 1);
  assert.ok(w.objects.has(w.row.resume_storage_path));
  assert.ok(w.row.resume_storage_path.startsWith(`${UID}/`));
  assert.equal(w.row.resume_filename, 'My CV.pdf');
  assert.equal(w.row.resume_content_type, 'application/pdf');
});

test('replacing a CV keeps one file and turns auto-submit off', async () => {
  const w = world(CONFIRMED);
  const result = await run(w, 'uploadCv', { cv: pdf() });
  ok(result);
  assert.match(result.message, /Automatic submission is off/);
  assert.deepEqual([...w.objects], [w.row.resume_storage_path]);
  assert.notEqual(w.row.resume_storage_path, OLD_PATH);
  assert.equal(w.row.resume_confirmed_at, null);
  assert.equal(w.row.auto_apply_mode, 'approval_required');
});

test('invalid uploads write nothing', async () => {
  for (const cv of [new File(['MZ'], 'a.pdf'), new File([], 'a.pdf'), new File(['%PDF-'], 'a.exe'), 'not a file']) {
    const w = world(CONFIRMED);
    refused(await run(w, 'uploadCv', { cv }), 400);
    assert.deepEqual(w.calls, []);
  }
});

test('the old CV is removed only after the row points at the new one', async () => {
  const w = world(CONFIRMED);
  await run(w, 'uploadCv', { cv: pdf() });
  assert.deepEqual(
    w.calls.map(([name]) => name),
    ['upload', 'update', 'remove']
  );
});

test('failures before the row update leave the old CV confirmed', async () => {
  for (const fail of [{ read: true }, { upload: true }, { update: { code: '42501', message: 'denied' } }]) {
    const w = world(CONFIRMED, fail);
    refused(await run(w, 'uploadCv', { cv: pdf() }), 500);
    assert.deepEqual([...w.objects], [OLD_PATH]);
    assert.equal(w.row.resume_confirmed_at, 'C0');
    assert.equal(w.row.auto_apply_mode, 'auto_submit');
  }
});

test('a lost connection never leaves the row pointing at a deleted file', async () => {
  for (const updateApplied of [true, false]) {
    const w = world(CONFIRMED, { update: { code: '', message: 'fetch failed' }, updateApplied });
    refused(await run(w, 'uploadCv', { cv: pdf() }), 500, /Reload/);
    assert.ok(w.objects.has(w.row.resume_storage_path));
  }
});

test('failing to remove the replaced CV is not an error', async () => {
  ok(await run(world(CONFIRMED, { remove: true }), 'uploadCv', { cv: pdf() }));
});

test('download keeps the original filename, encoded once', async () => {
  for (const name of ['My CV.pdf', 'R&D CV #2.pdf', 'C++ 100%.pdf', 'Ștefan.pdf']) {
    const w = world({ ...CONFIRMED, resume_filename: name });
    await assert.rejects(run(w, 'downloadCv'), (thrown) => {
      assert.equal(thrown.status, 303);
      const url = new URL(thrown.location);
      assert.equal(url.searchParams.get('download'), name);
      assert.equal(url.searchParams.get('token'), 'T');
      return true;
    });
    assert.deepEqual(w.calls, [['sign', OLD_PATH, 60]]);
  }
});

test('download failures', async () => {
  refused(await run(world(), 'downloadCv'), 404);
  refused(await run(world(CONFIRMED, { sign: true }), 'downloadCv'), 500);
  refused(await run(world(CONFIRMED, { read: true }), 'downloadCv'), 500);
});

test('confirm accepts only the CV that was displayed', async () => {
  const current = world(UNCONFIRMED);
  ok(await run(current, 'confirmCv', { resumeUploadedAt: 'T0' }));
  assert.ok(current.row.resume_confirmed_at);
  const stale = world(UNCONFIRMED);
  refused(await run(stale, 'confirmCv', { resumeUploadedAt: 'older' }), 409);
  assert.equal(stale.row.resume_confirmed_at, null);
});

test('confirm lists what is missing', async () => {
  const confirm = (row) => run(world(row), 'confirmCv', { resumeUploadedAt: 'T0' });
  const withAnswers = (changes) => ({
    ...UNCONFIRMED,
    screening_defaults: { ...UNCONFIRMED.screening_defaults, ...changes }
  });
  refused(
    await confirm({ resume_uploaded_at: 'T0' }),
    400,
    /a CV, your first and last name, work authorization, visa sponsorship/
  );
  refused(await confirm(withAnswers({ full_name: 'Jane' })), 400, /last name/);
  refused(await confirm(withAnswers({ work_authorization: 'yes' })), 400, /work authorization/);
  refused(await run(world(UNCONFIRMED), 'confirmCv'), 400);
});

test('auto-submit needs a confirmed CV', async () => {
  const fields = { autoApplyMode: 'auto_submit', maxDailyApplications: '25' };
  const unconfirmed = world(UNCONFIRMED);
  refused(await run(unconfirmed, 'saveAutoApply', fields), 400, /Confirm/);
  assert.deepEqual(unconfirmed.calls, []);
  const confirmed = world({ ...UNCONFIRMED, resume_confirmed_at: 'C' });
  ok(await run(confirmed, 'saveAutoApply', fields));
  assert.equal(confirmed.row.max_daily_applications, 25);
});

test('auto-apply input is validated', async () => {
  for (const cap of ['4', '26', '', '5.5', '1e1', '-5', '0x10']) {
    refused(await run(world(), 'saveAutoApply', { autoApplyMode: 'disabled', maxDailyApplications: cap }), 400);
  }
  refused(await run(world(), 'saveAutoApply', { autoApplyMode: 'other', maxDailyApplications: '5' }), 400);
  refused(await run(world(), 'saveAutoApply', { maxDailyApplications: '5' }), 400);
  ok(await run(world(), 'saveAutoApply', { autoApplyMode: 'disabled', maxDailyApplications: '5' }));
});

const STORED = {
  screening_defaults: { custom: 1, full_name: 'A B', years_experience: 3 },
  profile_filters: { custom: 1, titles: ['a'] },
  resume_data: { skills: ['python'], phone: '1', urls: { twitter: 't', github: 'https://g.example' } }
};

test('absent fields leave stored values alone', async () => {
  const w = world(STORED);
  ok(await run(w, 'savePreferences'));
  const { screening_defaults, profile_filters, resume_data } = w.row;
  assert.deepEqual({ screening_defaults, profile_filters, resume_data }, STORED);
});

test('saving merges, and empty optional fields are removed', async () => {
  const w = world(STORED);
  ok(
    await run(w, 'savePreferences', {
      fullName: 'Jane Doe',
      phone: '',
      location: 'London',
      github: '',
      linkedin: 'https://l.example/x',
      requiresSponsorship: 'no',
      workAuth: 'yes',
      yearsExperience: '0',
      noticePeriodDays: '365'
    })
  );
  assert.deepEqual(w.row.resume_data, {
    skills: ['python'],
    location: 'London', // never in screening_defaults, where it would answer "relocation" questions
    urls: { twitter: 't', linkedin: 'https://l.example/x' }
  });
  assert.deepEqual(w.row.screening_defaults, {
    custom: 1,
    full_name: 'Jane Doe',
    years_experience: 0,
    work_authorization: true,
    requires_sponsorship: false,
    notice_period_days: 365
  });
  ok(await run(w, 'savePreferences', { yearsExperience: '', fullName: '' }));
  assert.ok(!('years_experience' in w.row.screening_defaults));
  assert.equal(w.row.screening_defaults.full_name, 'Jane Doe');
});

test('invalid preferences write nothing', async () => {
  for (const fields of [
    { fullName: 'Jane' },
    { fullName: `J ${'x'.repeat(130)}` },
    { phone: '1'.repeat(121) },
    { linkedin: 'javascript:alert(1)' },
    { github: 'github.com/x' },
    { portfolio: `https://${'a'.repeat(300)}` },
    { requiresSponsorship: 'maybe' },
    { workAuth: 'maybe' },
    { yearsExperience: '51' },
    { yearsExperience: 'two' },
    { yearsExperience: '1.5' },
    { noticePeriodDays: '366' },
    { noticePeriodDays: '-1' }
  ]) {
    const w = world(STORED);
    refused(await run(w, 'savePreferences', fields), 400);
    assert.deepEqual(w.calls, []);
  }
});

test('trigger messages reach the user', async () => {
  refused(await run(world({ auto_apply_mode: 'auto_submit' }), 'savePreferences', { phone: '1' }), 400, /Confirm your CV/);
});

test('demo sessions store nothing', async () => {
  for (const [action, fields] of [
    ['savePreferences', {}],
    ['uploadCv', { cv: pdf() }],
    ['downloadCv', {}],
    ['confirmCv', { resumeUploadedAt: 'T0' }],
    ['saveAutoApply', { autoApplyMode: 'disabled', maxDailyApplications: '5' }]
  ]) {
    const w = world(CONFIRMED);
    w.locals.user.id = 'demo-user-id';
    ok(await run(w, action, fields));
    assert.deepEqual(w.calls, []);
  }
});

test('load returns the saved values, or an error instead of mock data', async () => {
  const { profile } = await load(world({ ...UNCONFIRMED, resume_data: STORED.resume_data }));
  assert.equal(profile.resume_uploaded_at_raw, 'T0');
  assert.equal(profile.requires_sponsorship, 'no');
  assert.equal(profile.github, 'https://g.example');
  assert.deepEqual(await load(world({}, { read: true })), { profile: null, loadError: true });
});
