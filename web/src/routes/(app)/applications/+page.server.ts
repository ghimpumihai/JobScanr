import { fail } from '@sveltejs/kit';
import type { PageServerLoad, Actions } from './$types';
import type { ApplicationRecord, ApplicationStatus, ATSPlatform } from '$lib/types';
import { isSupabaseConfigured } from '$lib/supabase/server';
import { safeHttpUrl } from '$lib/safeUrl';
import { checkSession, isAllowlisted, isEnabled, RemoteError, startSession } from '$lib/server/remoteApply/session';

// Employers accept applications only with their own API key (#48), so every application is applied to by hand.
const TABS = {
  to_apply: 'manual_apply',
  applied: 'submitted',
  not_interested: 'dismissed',
  closed: 'stale_closed'
} as const satisfies Record<string, ApplicationStatus>;
type Tab = keyof typeof TABS;

const PLATFORMS: ATSPlatform[] = ['greenhouse', 'lever', 'workday', 'ashby', 'smartrecruiters', 'teamtailor', 'google'];
const PAGE_SIZE = 50;
const MAX_COMPANY_LENGTH = 100;
// Inner joins, so filters on the company and platform drop non-matching rows instead of only blanking the join.
const COLUMNS =
  'id, status, created_at, applied_at, job_postings!inner(title, location, url, last_seen_at, companies!inner(name, ats_platform))';

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
  submitted: 'Marked as applied.',
  dismissed: 'Marked as not interested.',
  manual_apply: 'Moved back to To Apply.'
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
const DEMO_ROWS: ApplicationRecord[] = [
  demoRow(101, 'manual_apply', 'Junior Backend Engineer', 'Spotify', 'greenhouse', 'Stockholm / London'),
  demoRow(102, 'manual_apply', 'Software Engineer 1', 'Revolut', 'lever', 'London (Hybrid)'),
  demoRow(103, 'manual_apply', 'Graduate Software Engineer', 'Salesforce', 'workday', 'Dublin'),
  { ...demoRow(104, 'submitted', 'Associate Systems Engineer', 'Cloudflare', 'greenhouse', 'London'), applied_at: '2026-11-21T09:30:00Z' },
  demoRow(105, 'dismissed', 'Frontend Developer', 'Synthesia', 'ashby', 'Remote'),
  { ...demoRow(106, 'stale_closed', 'Platform Engineer', 'Datadog', 'greenhouse', 'Paris'), last_seen_at: '2026-10-01T06:00:00Z' }
];

function demoRow(
  id: number,
  status: ApplicationStatus,
  title: string,
  company_name: string,
  ats_platform: ATSPlatform,
  location: string
): ApplicationRecord {
  return {
    id,
    status,
    title,
    company_name,
    location,
    ats_platform,
    url: 'https://example.com/jobs/demo',
    added_at: '2026-11-20T06:00:00Z',
    applied_at: null,
    last_seen_at: '2026-11-22T06:00:00Z'
  };
}

function isLiveUser(locals: App.Locals): boolean {
  return Boolean(locals.user && locals.supabase && isSupabaseConfigured() && locals.user.id !== 'demo-user-id');
}

/** A real calendar day as YYYY-MM-DD, else undefined. */
function parseDay(raw: string | null): Date | undefined {
  const m = raw?.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return undefined;
  const day = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  return day.getUTCMonth() === +m[2] - 1 && day.getUTCDate() === +m[3] ? day : undefined;
}

/** Invalid values are ignored, so a bad link still shows the list. */
function parseFilters(url: URL) {
  const get = (name: string) => url.searchParams.get(name);
  const tab = (Object.keys(TABS) as Tab[]).find((t) => t === get('tab')) ?? 'to_apply';
  const platform = PLATFORMS.find((p) => p === get('platform'));
  const companyRaw = get('company')?.trim() ?? '';
  const company = companyRaw && companyRaw.length <= MAX_COMPANY_LENGTH ? companyRaw : '';
  const from = parseDay(get('from'));
  const to = parseDay(get('to'));
  const pageRaw = get('page') ?? '';
  const page = /^\d{1,4}$/.test(pageRaw) && +pageRaw >= 1 ? +pageRaw : 1;
  return { tab, platform, company, from, to, page };
}
type Filters = ReturnType<typeof parseFilters>;

// The Supabase builder's generic type changes with every filter, so it is not spelled out.
function applyFilters(query: any, f: Filters, status: ApplicationStatus) {
  let q = query.eq('status', status);
  if (f.platform) q = q.eq('job_postings.companies.ats_platform', f.platform);
  // PostgREST reads * as a wildcard and cannot escape it; \ % _ are escaped for LIKE.
  const company = f.company.replaceAll('*', '').replace(/[\\%_]/g, '\\$&');
  if (company) q = q.ilike('job_postings.companies.name', `%${company}%`);
  const dateColumn = status === 'submitted' ? 'applied_at' : 'created_at';
  if (f.from) q = q.gte(dateColumn, f.from.toISOString());
  if (f.to) q = q.lt(dateColumn, new Date(f.to.getTime() + 86_400_000).toISOString()); // "to" includes its day
  return q;
}

export const load: PageServerLoad = async ({ locals, url }) => {
  const f = parseFilters(url);
  const shown = {
    tab: f.tab,
    filters: {
      platform: f.platform ?? '',
      company: f.company,
      from: f.from?.toISOString().slice(0, 10) ?? '',
      to: f.to?.toISOString().slice(0, 10) ?? ''
    },
    page: f.page,
    pageSize: PAGE_SIZE
  };

  if (!isLiveUser(locals)) {
    const counts = Object.fromEntries(
      (Object.keys(TABS) as Tab[]).map((t) => [t, DEMO_ROWS.filter((r) => r.status === TABS[t]).length])
    ) as Record<Tab, number>;
    const applications = DEMO_ROWS.filter((r) => r.status === TABS[f.tab]);
    // Shown in demo only while the trial is switched on, so the panel can be reviewed; its actions refuse demo mode.
    return { ...shown, applications, counts, profile: DEMO_PROFILE, loadError: false, demo: true, remoteApply: isEnabled() };
  }

  const status = TABS[f.tab];
  const start = (f.page - 1) * PAGE_SIZE;
  const rowsQuery = applyFilters(locals.supabase.from('applications').select(COLUMNS), f, status)
    .order('created_at', { ascending: false })
    .order('id', { ascending: false })
    .range(start, start + PAGE_SIZE - 1);
  const countQueries = (Object.keys(TABS) as Tab[]).map((t) =>
    applyFilters(locals.supabase.from('applications').select(COLUMNS, { count: 'exact', head: true }), f, TABS[t])
  );
  const profileQuery = locals.supabase
    .from('users')
    .select('id, email, resume_filename, screening_defaults, resume_data')
    .eq('auth_user_id', locals.user!.id)
    .single();

  const [rows, profileResult, ...countResults] = await Promise.all([rowsQuery, profileQuery, ...countQueries]);
  const failed = [rows, profileResult, ...countResults].find((r) => r.error);
  if (failed || !rows.data || !profileResult.data) {
    console.error('Failed to load applications:', failed?.error?.message);
    const counts = { to_apply: 0, applied: 0, not_interested: 0, closed: 0 };
    return { ...shown, applications: [], counts, profile: null, loadError: true, demo: false, remoteApply: false };
  }

  // Nested join rows are untyped.
  const applications: ApplicationRecord[] = rows.data.map((row: any) => ({
    id: row.id,
    status: row.status,
    title: row.job_postings?.title ?? 'Unknown role',
    company_name: row.job_postings?.companies?.name ?? 'Unknown company',
    location: row.job_postings?.location ?? '',
    ats_platform: row.job_postings?.companies?.ats_platform,
    url: safeHttpUrl(row.job_postings?.url),
    added_at: row.created_at,
    applied_at: row.applied_at,
    last_seen_at: row.job_postings?.last_seen_at ?? null
  }));
  const counts = Object.fromEntries(
    (Object.keys(TABS) as Tab[]).map((t, i) => [t, countResults[i].count ?? 0])
  ) as Record<Tab, number>;

  const p = profileResult.data;
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
  return { ...shown, applications, counts, profile, loadError: false, demo: false, remoteApply: isEnabled() && isAllowlisted(p.id) };
};

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

  // Remote-browser apply spike (#129): fill the employer's form in a live view; the user clicks Submit.
  remoteStart: ({ request, locals }) =>
    remote(request, locals, (sb, id) => startSession(sb, locals.user!.id, id)),
  remotePoll: ({ request, locals }) => remote(request, locals, (sb, id) => checkSession(sb, id)),
  remoteEnd: ({ request, locals }) => remote(request, locals, (sb, id) => checkSession(sb, id, true))
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
