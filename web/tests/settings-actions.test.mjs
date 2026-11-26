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
const WITH_CV = {
  resume_storage_path: OLD_PATH,
  resume_filename: 'My CV.pdf',
  resume_uploaded_at: 'T0',
  auto_apply_mode: 'approval_required',
  screening_defaults: { full_name: 'Jane Doe', work_authorization: true, requires_sponsorship: false }
};

// No platform accepts applications without the employer's key (#48), so the mode is refused outright.
function applyTrigger(before, next) {
  if (next.auto_apply_mode === 'auto_submit') return { code: 'P0001', message: 'Automatic submission is not available' };
  return null;
}

/** fail: { read, upload, remove, sign: true } or { update: error, updateApplied: true if the row still changed }. */
function world(row = {}, fail = {}, answers = []) {
  const w = {
    objects: new Set(),
    calls: [],
    answers: structuredClone(answers),
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
  // user_answers: row-level security shows a user only their own rows (user_id = their users.id).
  function answersQuery() {
    let op = 'select';
    let patch;
    const filters = [];
    const run = () => {
      if (fail.answers) return failure;
      const hit = w.answers.filter((a) => a.user_id === w.row.id && filters.every(([k, v]) => a[k] === v));
      if (op === 'update') {
        w.calls.push(['update answer', patch.answer, filters]);
        hit.forEach((a) => Object.assign(a, patch));
      } else if (op === 'delete') {
        w.calls.push(['delete answer', filters]);
        w.answers = w.answers.filter((a) => !hit.includes(a));
      }
      if (op !== 'select') return { data: hit.map((a) => ({ id: a.id })), error: null };
      return { data: hit.map(({ id, question, answer, first_seen_at }) => ({ id, question, answer, first_seen_at })), error: null };
    };
    const b = {
      select: () => b,
      update: (value) => ((op = 'update'), (patch = value), b),
      delete: () => ((op = 'delete'), b),
      eq: (key, value) => (filters.push([key, value]), b),
      order: () => b,
      then: (resolve, reject) => Promise.resolve(run()).then(resolve, reject)
    };
    return b;
  }
  w.locals = {
    user: { id: UID },
    supabase: { from: (table) => (table === 'user_answers' ? answersQuery() : query()), storage: { from: () => bucket } }
  };
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

test('replacing a CV keeps one file and promises nothing about submission', async () => {
  const w = world(WITH_CV);
  const result = await run(w, 'uploadCv', { cv: pdf() });
  ok(result);
  assert.equal(result.message, 'CV uploaded.');
  assert.deepEqual([...w.objects], [w.row.resume_storage_path]);
  assert.notEqual(w.row.resume_storage_path, OLD_PATH);
});

test('invalid uploads write nothing', async () => {
  for (const cv of [new File(['MZ'], 'a.pdf'), new File([], 'a.pdf'), new File(['%PDF-'], 'a.exe'), 'not a file']) {
    const w = world(WITH_CV);
    refused(await run(w, 'uploadCv', { cv }), 400);
    assert.deepEqual(w.calls, []);
  }
});

test('the old CV is removed only after the row points at the new one', async () => {
  const w = world(WITH_CV);
  await run(w, 'uploadCv', { cv: pdf() });
  assert.deepEqual(
    w.calls.map(([name]) => name),
    ['upload', 'update', 'remove']
  );
});

test('failures before the row update leave the old CV in place', async () => {
  for (const fail of [{ read: true }, { upload: true }, { update: { code: '42501', message: 'denied' } }]) {
    const w = world(WITH_CV, fail);
    refused(await run(w, 'uploadCv', { cv: pdf() }), 500);
    assert.deepEqual([...w.objects], [OLD_PATH]);
    assert.equal(w.row.resume_storage_path, OLD_PATH);
  }
});

test('a lost connection never leaves the row pointing at a deleted file', async () => {
  for (const updateApplied of [true, false]) {
    const w = world(WITH_CV, { update: { code: '', message: 'fetch failed' }, updateApplied });
    refused(await run(w, 'uploadCv', { cv: pdf() }), 500, /Reload/);
    assert.ok(w.objects.has(w.row.resume_storage_path));
  }
});

test('failing to remove the replaced CV is not an error', async () => {
  ok(await run(world(WITH_CV, { remove: true }), 'uploadCv', { cv: pdf() }));
});

test('download keeps the original filename, encoded once', async () => {
  for (const name of ['My CV.pdf', 'R&D CV #2.pdf', 'C++ 100%.pdf', 'Ștefan.pdf']) {
    const w = world({ ...WITH_CV, resume_filename: name });
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
  refused(await run(world(WITH_CV, { sign: true }), 'downloadCv'), 500);
  refused(await run(world(WITH_CV, { read: true }), 'downloadCv'), 500);
});

test('only Active and Paused can be saved, and no daily limit is written', async () => {
  for (const autoApplyMode of ['auto_submit', 'other', '']) {
    const w = world();
    refused(await run(w, 'saveAutoApply', { autoApplyMode }), 400);
    assert.deepEqual(w.calls, []);
  }
  for (const autoApplyMode of ['approval_required', 'disabled']) {
    const w = world({ max_daily_applications: 10 });
    ok(await run(w, 'saveAutoApply', { autoApplyMode, maxDailyApplications: '25' }));
    assert.deepEqual(w.calls, [['update', { auto_apply_mode: autoApplyMode }]]);
    assert.equal(w.row.max_daily_applications, 10);
  }
  assert.equal(actions.confirmCv, undefined);
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
  refused(await run(world({ auto_apply_mode: 'auto_submit' }), 'savePreferences', { phone: '1' }), 400, /not available/);
});

test('demo sessions store nothing', async () => {
  for (const [action, fields] of [
    ['savePreferences', {}],
    ['uploadCv', { cv: pdf() }],
    ['downloadCv', {}],
    ['saveAutoApply', { autoApplyMode: 'disabled' }],
    ['saveDrafts', { llmDrafts: 'true' }],
    ['saveAnswer', { id: '1', answer: 'From March' }],
    ['deleteAnswer', { id: '1' }]
  ]) {
    const w = world(WITH_CV);
    w.locals.user.id = 'demo-user-id';
    ok(await run(w, action, fields));
    assert.deepEqual(w.calls, []);
  }
});

test('the drafts opt-in saves on and off, and nothing else', async () => {
  const w = world({ llm_drafts_enabled: false });
  ok(await run(w, 'saveDrafts', { llmDrafts: 'true' }));
  assert.equal(w.row.llm_drafts_enabled, true);
  ok(await run(w, 'saveDrafts', {})); // an unchecked box sends nothing
  ok(await run(w, 'saveDrafts', { llmDrafts: 'yes' }));
  assert.deepEqual(w.calls, [
    ['update', { llm_drafts_enabled: true }],
    ['update', { llm_drafts_enabled: false }],
    ['update', { llm_drafts_enabled: false }]
  ]);
  refused(await run(world({}, { update: { message: 'x' } }), 'saveDrafts', { llmDrafts: 'true' }), 500);
});

test('load shows the drafts card only to remote fill users', async () => {
  process.env.REMOTE_APPLY_ENABLED = 'true';
  process.env.REMOTE_APPLY_USER_IDS = '1';
  try {
    const loaded = await load(world({ llm_drafts_enabled: true }));
    assert.equal(loaded.profile.llm_drafts_enabled, true);
    assert.equal(loaded.remoteApply, true);
    process.env.REMOTE_APPLY_USER_IDS = '2';
    assert.equal((await load(world())).remoteApply, false);
    assert.equal((await load(world())).profile.llm_drafts_enabled, false); // column missing or null: off
    process.env.REMOTE_APPLY_ENABLED = 'false';
    process.env.REMOTE_APPLY_USER_IDS = '1';
    assert.equal((await load(world())).remoteApply, false);
  } finally {
    delete process.env.REMOTE_APPLY_ENABLED;
    delete process.env.REMOTE_APPLY_USER_IDS;
  }
});

const ANSWERS = [
  { id: 1, user_id: 1, question: 'What are your salary expectations?', answer: '60,000 EUR', first_seen_at: 'T1' },
  { id: 2, user_id: 1, question: 'When can you start?', answer: null, first_seen_at: 'T2' },
  { id: 3, user_id: 2, question: 'Someone else', answer: 'secret', first_seen_at: 'T0' }
];

test('saved answers load own rows only, pending first', async () => {
  const { answers } = await load(world({}, {}, ANSWERS));
  assert.deepEqual(answers.map((a) => a.id), [2, 1]);
  const failed = await load(world({}, { answers: true }, ANSWERS)); // a failed read hides the rows, not the page
  assert.deepEqual([failed.loadError, failed.answers], [false, []]);
});

test('answering, editing and deleting a saved question', async () => {
  const w = world({}, {}, ANSWERS);
  ok(await run(w, 'saveAnswer', { id: '2', answer: '  From March  ' }));
  ok(await run(w, 'saveAnswer', { id: '1', answer: '65,000 EUR' }));
  assert.deepEqual(w.answers.map((a) => a.answer), ['65,000 EUR', 'From March', 'secret']);
  ok(await run(w, 'deleteAnswer', { id: '2' }));
  assert.deepEqual(w.answers.map((a) => a.id), [1, 3]);
  assert.ok(w.answers.every((a) => a.id !== 2));
});

test('bad answers and other users\' questions are refused', async () => {
  const w = world({}, {}, ANSWERS);
  refused(await run(w, 'saveAnswer', { id: '1', answer: '' }), 400, /1 to 1000/);
  refused(await run(w, 'saveAnswer', { id: '1', answer: 'x'.repeat(1001) }), 400);
  refused(await run(w, 'saveAnswer', { id: 'abc', answer: 'x' }), 400);
  refused(await run(w, 'deleteAnswer', { id: '0' }), 400);
  assert.deepEqual(w.calls, []);
  refused(await run(w, 'saveAnswer', { id: '3', answer: 'mine now' }), 404);
  refused(await run(w, 'deleteAnswer', { id: '3' }), 404);
  refused(await run(w, 'deleteAnswer', { id: '99' }), 404);
  assert.equal(w.answers.find((a) => a.id === 3).answer, 'secret');
  refused(await run(world({}, { answers: true }, ANSWERS), 'saveAnswer', { id: '1', answer: 'x' }), 500);
});

test('load returns the saved values, or an error instead of mock data', async () => {
  const { profile } = await load(world({ ...WITH_CV, resume_data: STORED.resume_data }));
  assert.equal(profile.resume_uploaded_at_raw, 'T0');
  assert.equal(profile.requires_sponsorship, 'no');
  assert.equal(profile.github, 'https://g.example');
  assert.deepEqual(await load(world({}, { read: true })), { profile: null, loadError: true });
});
