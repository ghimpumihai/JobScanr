import { fail } from '@sveltejs/kit';
import type { PageServerLoad, Actions } from './$types';
import type { ApplicationRecord, ApplicationStatus, ATSPlatform } from '$lib/types';
import { isSupabaseConfigured } from '$lib/supabase/server';
import { safeHttpUrl } from '$lib/safeUrl';
import { checkSession, DAILY_CAP, isAllowlisted, isEnabled, RemoteError, startSession } from '$lib/server/remoteApply/session';
import { redraft } from '$lib/server/remoteApply/redraft';

// Employers accept applications only with their own API key (#48), so every application is applied to by hand.
// The Inbox (#141) is To Apply; roles stay there until the user decides.
const TABS = {
  inbox: 'manual_apply',
  applied: 'submitted',
  not_interested: 'dismissed',
  closed: 'stale_closed'
} as const satisfies Record<string, ApplicationStatus>;
type Tab = keyof typeof TABS;

// shortcut: search and the platform filter run in the browser over the newest ROW_LIMIT rows of a tab; move them
// into the query (and page) once a user keeps more than this many roles in one tab.
const ROW_LIMIT = 500;
const COLUMNS =
  'id, status, created_at, applied_at, opened_at, job_postings!inner(title, location, url, compensation, last_seen_at, companies!inner(name, ats_platform))';

// The same pairs as protect_application_queue_fields in db/schema.sql, which is the real check.
const ALLOWED: [ApplicationStatus, ApplicationStatus][] = [
  ['manual_apply', 'submitted'],
  ['stale_closed', 'submitted'],
  ['manual_apply', 'dismissed'],
  ['stale_closed', 'dismissed'],
  ['dismissed', 'manual_apply'],
  ['submitted', 'manual_apply']
];
const DONE: Record<string, string> = {
  submitted: 'moved to Applied.',
  dismissed: 'moved to Not interested.',
  manual_apply: 'moved back to Inbox.'
};
const DEMO_RESULT = { success: true, message: 'Demo mode: nothing is stored.', undo: null };

const DEMO_PROFILE = {
  full_name: 'Stefan Ghimpu',
  email: 'stefan@example.com',
  phone: '+40 700 000 000',
  location: 'Bucharest, Romania',
  linkedin: 'https://linkedin.com/in/example',
  github: 'https://github.com/example',
  portfolio: '',
  resume_filename: 'stefan_ghimpu_cv_2026.pdf'
};
const DEMO_FILTERS = { levels: ['junior', 'graduate', 'new grad', 'intern'], titles: ['Backend', 'Software Engineer'], locations: ['London', 'Dublin', 'Remote'] };

function demoRows(now: Date): ApplicationRecord[] {
  const ago = (days: number) => new Date(now.getTime() - days * 86_400_000).toISOString();
  const row = (id: number, status: ApplicationStatus, title: string, company_name: string, ats_platform: ATSPlatform, location: string, compensation: string | null, days: number, opened: boolean): ApplicationRecord => ({
    id, status, title, company_name, location, ats_platform, compensation,
    url: 'https://example.com/jobs/demo',
    added_at: ago(days),
    applied_at: status === 'submitted' ? ago(days - 1) : null,
    opened_at: opened ? ago(days) : null,
    last_seen_at: status === 'stale_closed' ? ago(days - 3) : ago(0),
    matched: matchedOn(title, location, DEMO_FILTERS)
  });
  return [
    row(101, 'manual_apply', 'Junior Backend Engineer', 'Spotify', 'greenhouse', 'Stockholm / London', '€55–65k', 0, false),
    row(102, 'manual_apply', 'New Grad Software Engineer', 'Revolut', 'lever', 'London (Hybrid)', '£60k', 0, false),
    row(103, 'manual_apply', 'Junior Full-Stack Engineer', 'Synthesia', 'ashby', 'London / Remote', '£55–62k', 1, false),
    row(104, 'manual_apply', 'Graduate Software Engineer', 'Salesforce', 'workday', 'Dublin', null, 1, true),
    row(105, 'manual_apply', 'Software Engineer Intern, Summer 2027', 'Bolt', 'smartrecruiters', 'Tallinn', null, 4, true),
    row(106, 'submitted', 'Associate Systems Engineer', 'Cloudflare', 'greenhouse', 'London', '£58–66k', 7, true),
    row(107, 'dismissed', 'Frontend Developer', 'Pleo', 'ashby', 'Remote', null, 8, true),
    row(108, 'stale_closed', 'Platform Engineer', 'Datadog', 'greenhouse', 'Paris', '€62–70k', 40, true)
  ];
}

type Filters = { levels?: unknown; titles?: unknown; locations?: unknown };
/** The user's own filter words found in this role, for "Matched on". The matcher (jobs/match.py) is the real check. */
function matchedOn(title: string, location: string, f: Filters | null | undefined): string[] {
  const words = (v: unknown) => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string' && x.trim() !== '') : []);
  const has = (text: string, w: string) => text.toLowerCase().includes(w.toLowerCase());
  const found = [
    ...words(f?.levels).filter((w) => has(title, w)),
    ...words(f?.titles).filter((w) => has(title, w)),
    ...words(f?.locations).filter((w) => has(location, w))
  ].map((w) => w.charAt(0).toUpperCase() + w.slice(1));
  return [...new Set(found)].slice(0, 6);
}

/** Named in the consent notice, so users know which company runs the browser. */
function remoteProviderLabel(): string {
  return process.env.REMOTE_APPLY_PROVIDER === 'cloudflare' ? 'Cloudflare' : 'Browserbase';
}

function isLiveUser(locals: App.Locals): boolean {
  return Boolean(locals.user && locals.supabase && isSupabaseConfigured() && locals.user.id !== 'demo-user-id');
}

const parseTab = (url: URL): Tab => (Object.keys(TABS) as Tab[]).find((t) => t === url.searchParams.get('tab')) ?? 'inbox';

export const load: PageServerLoad = async ({ locals, url }) => {
  const tab = parseTab(url);

  if (!isLiveUser(locals)) {
    const all = demoRows(new Date());
    const counts = Object.fromEntries((Object.keys(TABS) as Tab[]).map((t) => [t, all.filter((r) => r.status === TABS[t]).length])) as Record<Tab, number>;
    const applications = all.filter((r) => r.status === TABS[tab]);
    // Shown in demo only while the trial is switched on, so the panel can be reviewed; its actions refuse demo mode.
    return { tab, applications, counts, profile: DEMO_PROFILE, loadError: false, demo: true, remoteApply: isEnabled(), remoteProvider: remoteProviderLabel(), fillsLeft: DAILY_CAP };
  }

  const status = TABS[tab];
  const rowsQuery = locals.supabase
    .from('applications')
    .select(COLUMNS)
    .eq('status', status)
    .order('created_at', { ascending: false })
    .order('id', { ascending: false })
    .range(0, ROW_LIMIT - 1);
  const countQueries = (Object.keys(TABS) as Tab[]).map((t) =>
    locals.supabase.from('applications').select('id', { count: 'exact', head: true }).eq('status', TABS[t])
  );
  const profileQuery = locals.supabase
    .from('users')
    .select('id, email, resume_filename, screening_defaults, resume_data, profile_filters')
    .eq('auth_user_id', locals.user!.id)
    .single();

  const [rows, profileResult, ...countResults] = await Promise.all([rowsQuery, profileQuery, ...countQueries]);
  const failed = [rows, profileResult, ...countResults].find((r) => r.error);
  if (failed || !rows.data || !profileResult.data) {
    console.error('Failed to load applications:', failed?.error?.message);
    const counts = { inbox: 0, applied: 0, not_interested: 0, closed: 0 };
    return { tab, applications: [], counts, profile: null, loadError: true, demo: false, remoteApply: false, remoteProvider: '', fillsLeft: 0 };
  }

  const p = profileResult.data;
  // Nested join rows are untyped.
  const applications: ApplicationRecord[] = rows.data.map((row: any) => {
    const title = row.job_postings?.title ?? 'Unknown role';
    const location = row.job_postings?.location ?? '';
    return {
      id: row.id,
      status: row.status,
      title,
      company_name: row.job_postings?.companies?.name ?? 'Unknown company',
      location,
      ats_platform: row.job_postings?.companies?.ats_platform,
      compensation: row.job_postings?.compensation || null,
      url: safeHttpUrl(row.job_postings?.url),
      added_at: row.created_at,
      applied_at: row.applied_at,
      opened_at: row.opened_at ?? null,
      last_seen_at: row.job_postings?.last_seen_at ?? null,
      matched: matchedOn(title, location, p.profile_filters)
    };
  });
  const counts = Object.fromEntries(
    (Object.keys(TABS) as Tab[]).map((t, i) => [t, countResults[i].count ?? 0])
  ) as Record<Tab, number>;

  const urls = p.resume_data?.urls ?? {};
  const text = (value: unknown) => (typeof value === 'string' ? value : '');
  const profile = {
    full_name: text(p.screening_defaults?.full_name),
    email: text(p.email),
    phone: text(p.resume_data?.phone),
    location: text(p.resume_data?.location),
    linkedin: text(urls.linkedin),
    github: text(urls.github),
    portfolio: text(urls.portfolio),
    resume_filename: text(p.resume_filename)
  };
  const remoteApply = isEnabled() && isAllowlisted(p.id);
  return { tab, applications, counts, profile, loadError: false, demo: false, remoteApply, remoteProvider: remoteProviderLabel(), fillsLeft: remoteApply ? await fillsLeft(locals.supabase, p.id) : 0 };
};

/** Fills left today: the same count startSession checks against DAILY_CAP. An unreadable count shows none left. */
async function fillsLeft(sb: App.Locals['supabase'], userId: number): Promise<number> {
  const midnight = new Date();
  midnight.setUTCHours(0, 0, 0, 0);
  const { count, error } = await sb
    .from('remote_apply_sessions')
    .select('id', { count: 'exact', head: true })
    .eq('user_id', userId)
    .gte('started_at', midnight.toISOString());
  if (error) console.error('Failed to count fills:', error.message);
  return error ? 0 : Math.max(0, DAILY_CAP - (count ?? 0));
}

export const actions: Actions = {
  setStatus: async ({ request, locals }) => {
    const form = await request.formData();
    const idRaw = form.get('id')?.toString() ?? '';
    const from = form.get('from')?.toString() as ApplicationStatus;
    const to = form.get('to')?.toString() as ApplicationStatus;
    if (!/^\d{1,15}$/.test(idRaw) || !ALLOWED.some(([a, b]) => a === from && b === to)) {
      return fail(400, { error: 'This change is not possible.' });
    }
    if (!isLiveUser(locals)) return DEMO_RESULT;
    const id = Number(idRaw);

    // Compare-and-set: a row another tab already changed matches nothing and is left alone.
    const { data, error } = await locals.supabase
      .from('applications')
      .update({ status: to })
      .eq('id', id)
      .eq('status', from)
      .select('id');
    if (error) {
      console.error('Status change failed:', error.message);
      if (!error.code) {
        return fail(503, { error: 'The connection failed, so the outcome is unknown. Reload to see this application.' });
      }
      // P0001 = RAISE EXCEPTION in protect_application_queue_fields, whose messages are written for users.
      if (error.code === 'P0001') return fail(400, { error: error.message });
      return fail(500, { error: 'Could not change this application. Please try again.' });
    }
    if (!data?.length) {
      return fail(409, { error: 'This application was already changed. Reload to see its current status.' });
    }
    // Undo always returns to To Apply: the database does not allow going back to Closed.
    const undo = to === 'manual_apply' ? null : { id, from: to, to: 'manual_apply' as const };
    return { success: true, message: DONE[to], undo };
  },

  // Clears the unread dot; the database stamps the time and never clears it (protect_application_queue_fields).
  markOpened: async ({ request, locals }) => {
    const idRaw = (await request.formData()).get('id')?.toString() ?? '';
    if (!/^\d{1,15}$/.test(idRaw)) return fail(400, { error: 'Unknown role.' });
    if (!isLiveUser(locals)) return { success: true };
    const { error } = await locals.supabase
      .from('applications')
      .update({ opened_at: new Date().toISOString() })
      .eq('id', Number(idRaw))
      .is('opened_at', null);
    if (error) console.error('Mark opened failed:', error.message); // only the dot stays; not worth an error
    return { success: true };
  },

  // Remote-browser apply spike (#129): fill the employer's form in a live view; the user clicks Submit.
  remoteStart: ({ request, locals }) =>
    remote(request, locals, (sb, id) => startSession(sb, locals.user!.id, id)),
  remotePoll: ({ request, locals }) => remote(request, locals, (sb, id) => checkSession(sb, id)),
  remoteEnd: ({ request, locals }) => remote(request, locals, (sb, id) => checkSession(sb, id, true)),
  // Redraft with a note (#142): `id` is the remote session; the note is sent to Groq once and never stored.
  remoteRedraft: async ({ request, locals }) => {
    const form = await request.clone().formData(); // remote() reads the body for the id
    const label = form.get('label')?.toString().trim() ?? '';
    const note = form.get('note')?.toString().trim() ?? '';
    return remote(request, locals, (sb, id) => redraft(sb, locals.user!.id, id, label, note));
  }
};

async function remote<T>(request: Request, locals: App.Locals, run: (sb: App.Locals['supabase'], id: number) => Promise<T>) {
  const idRaw = (await request.formData()).get('id')?.toString() ?? '';
  if (!/^\d{1,15}$/.test(idRaw)) return fail(400, { error: 'This change is not possible.' });
  if (!isLiveUser(locals)) return fail(400, { error: 'Fill it for me is not available in demo mode.' });
  try {
    return { remote: await run(locals.supabase, Number(idRaw)) };
  } catch (e) {
    if (e instanceof RemoteError) return fail(e.status, { error: e.message });
    console.error('Remote apply failed:', e instanceof Error ? e.name : 'Error');
    return fail(500, { error: 'Something went wrong. Use the Apply link instead.' });
  }
}
