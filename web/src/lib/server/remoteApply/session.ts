// Remote fill sessions for the apply spike (#129). JobScanr opens the employer's form in a remote browser,
// fills it, and hands the user a live view; the user always clicks Submit. Applied is recorded only from the
// employer's confirmation page, through the same user-scoped update as Mark as Applied.
// Every database call runs with the user's own Supabase session, so RLS and the status trigger apply.
import type { SupabaseClient } from '@supabase/supabase-js';
import { chromium, type Browser, type Page } from 'playwright-core';
import { MAX_CV_SIZE } from '$lib/cvFile';
import { safeHttpUrl } from '$lib/safeUrl';
import { captchaVisible, isConfirmation } from './detect';
import { fillPage, normalizeQuestion, type FillPlan, type FillProfile } from './fill';
import { getProvider, SESSION_SECONDS, type Connection, type RemoteProvider } from './provider';

export const DAILY_CAP = 5;
// Only the ATS-hosted form pages, so the remote browser is never sent anywhere else.
const FORM_HOSTS: Record<string, string> = {
  greenhouse: 'job-boards.greenhouse.io',
  lever: 'jobs.lever.co',
  ashby: 'jobs.ashbyhq.com'
};

/** Swapped in tests; nothing else changes them. */
export const deps = {
  /** No name: the one REMOTE_APPLY_PROVIDER picks, for new sessions. With a name: the one that made a session. */
  provider: (name?: string): RemoteProvider => getProvider(name),
  connect: (c: Connection): Promise<Browser> => chromium.connectOverCDP(c.url, { headers: c.headers }),
  fill: fillPage,
  captchaVisible,
  now: () => new Date()
};

export class RemoteError extends Error {
  constructor(
    readonly status: number,
    message: string
  ) {
    super(message);
  }
}

export interface StartResult {
  sessionId: number;
  liveViewUrl: string;
  /** Labels the user must answer: open-ended and unanswered questions, plus fields that could not be filled. */
  leftForUser: string[];
}

export type SessionState = 'open' | 'submitted' | 'abandoned' | 'expired' | 'error' | 'posting_gone';
/** What a check reports; `unrecorded`: the employer confirmed it, but marking it Applied failed. */
export type CheckState = SessionState | 'unrecorded';

export function isEnabled(): boolean {
  return process.env.REMOTE_APPLY_ENABLED === 'true';
}

export function isAllowlisted(userId: number): boolean {
  return (process.env.REMOTE_APPLY_USER_IDS ?? '').split(',').some((part) => part.trim() === String(userId));
}

/** The bare application form on the ATS's own host, or null. */
export function formUrl(platform: string, posting: { url?: string | null; external_id?: string; ats_identifier?: string }, plan: FillPlan | null): string | null {
  let url: string | null = null;
  if (platform === 'greenhouse') {
    url =
      plan?.posting_url ??
      (posting.ats_identifier && posting.external_id
        ? `https://job-boards.greenhouse.io/embed/job_app?${new URLSearchParams({ for: posting.ats_identifier, token: posting.external_id })}`
        : null);
  } else if (platform === 'lever' || platform === 'ashby') {
    const suffix = platform === 'lever' ? '/apply' : '/application';
    const base = (posting.url ?? '').split(/[?#]/)[0].replace(/\/+$/, '');
    url = base ? (base.endsWith(suffix) ? base : base + suffix) : null;
  }
  if (!url || safeHttpUrl(url) === '#') return null;
  const parsed = new URL(url);
  return parsed.protocol === 'https:' && parsed.hostname === FORM_HOSTS[platform] ? url : null;
}

// Error messages from a CDP connection can contain the connect URL and its key; log only the error's name.
const errorName = (e: unknown) => (e instanceof Error ? e.name : 'Error');

function text(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined;
}

async function firstPage(browser: Browser): Promise<Page> {
  const context = browser.contexts()[0];
  if (!context) throw new Error('no browser context');
  return context.pages().at(-1) ?? (await context.newPage());
}

export async function startSession(sb: SupabaseClient, authUserId: string, applicationId: number): Promise<StartResult> {
  if (!isEnabled()) throw new RemoteError(503, 'Fill it for me is switched off.');

  const { data: user, error: userError } = await sb
    .from('users')
    .select('id, email, resume_storage_path, resume_filename, screening_defaults, resume_data, llm_drafts_enabled')
    .eq('auth_user_id', authUserId)
    .single();
  if (userError || !user) throw new RemoteError(500, 'Could not load your profile.');
  if (!isAllowlisted(user.id)) throw new RemoteError(403, 'Fill it for me is only open to the trial group.');

  const { data: app } = await sb
    .from('applications')
    .select('id, status, job_postings!inner(url, external_id, companies!inner(ats_platform, ats_identifier))')
    .eq('id', applicationId)
    .single();
  if (!app) throw new RemoteError(404, 'Application not found.');
  if (app.status !== 'manual_apply') throw new RemoteError(409, 'Only applications in To Apply can be filled.');
  const posting: any = app.job_postings; // nested join rows are untyped
  const platform: string = posting?.companies?.ats_platform ?? '';
  if (!FORM_HOSTS[platform]) throw new RemoteError(422, 'Fill it for me works on Greenhouse, Lever and Ashby only.');

  const midnight = deps.now();
  midnight.setUTCHours(0, 0, 0, 0);
  const { count, error: countError } = await sb
    .from('remote_apply_sessions')
    .select('id', { count: 'exact', head: true })
    .eq('user_id', user.id)
    .gte('started_at', midnight.toISOString());
  if (countError) throw new RemoteError(500, 'Could not check your daily limit.');
  // shortcut: the count and the insert are separate requests, so two starts in the same second can both pass and a
  // user can reach DAILY_CAP + 1 or so; enforce it with an insert trigger before the pilot grows beyond ~5 users.
  if ((count ?? 0) >= DAILY_CAP) throw new RemoteError(429, `You have used all ${DAILY_CAP} fills for today.`);

  if (!user.resume_storage_path) throw new RemoteError(422, 'Upload a CV in Settings first.');
  const { data: blob, error: cvError } = await sb.storage.from('resumes').download(user.resume_storage_path);
  if (cvError || !blob) throw new RemoteError(502, 'Could not read your CV.');
  const buffer = Buffer.from(await blob.arrayBuffer()); // memory only (constitution 1.2)
  if (buffer.length > MAX_CV_SIZE) throw new RemoteError(422, 'Your CV is larger than 2 MB.');
  // The name the user uploaded, not the storage object's: employers see it.
  const cv = { name: text(user.resume_filename) ?? 'cv.pdf', mimeType: blob.type || 'application/pdf', buffer };

  const { data: planRow } = await sb.from('application_fill_plans').select('plan').eq('application_id', app.id).maybeSingle();
  const plan: FillPlan | null = planRow?.plan ?? null;
  // Opting out takes effect now, not at the next plan refresh (#59).
  if (!user.llm_drafts_enabled) for (const q of plan?.for_user ?? []) delete q.draft;
  // Answer memory: current answers, by the pipeline's link or else by the same question text (also old plans).
  const { data: memory } = await sb.from('user_answers').select('id, question_key, answer').eq('user_id', user.id);
  const byId = new Map((memory ?? []).map((m) => [m.id, m]));
  const byKey = new Map((memory ?? []).map((m) => [m.question_key, m]));
  for (const q of plan?.for_user ?? []) {
    if (q.reason !== 'no_confident_answer') continue;
    const linked = q.memory_id != null ? byId.get(q.memory_id) : undefined;
    const saved = linked ?? byKey.get(normalizeQuestion(q.label));
    if (!linked) q.memory_match = 'exact';
    if (typeof saved?.answer === 'string' && saved.answer.trim()) q.memory_answer = saved.answer;
  }
  const url = formUrl(platform, { url: posting.url, external_id: posting.external_id, ats_identifier: posting.companies?.ats_identifier }, plan);
  if (!url) throw new RemoteError(422, 'This posting has no form page JobScanr can open.');

  const urls = user.resume_data?.urls ?? {};
  const profile: FillProfile = {
    full_name: text(user.screening_defaults?.full_name),
    email: text(user.email),
    phone: text(user.resume_data?.phone),
    location: text(user.resume_data?.location),
    linkedin: text(urls.linkedin),
    github: text(urls.github),
    portfolio: text(urls.portfolio)
  };

  const provider = deps.provider();
  // A session nobody polled (the drawer closed while it was starting) would block this application for good:
  // expire its row and release its browser, in case the provider has not timed it out yet.
  const { data: stale } = await sb
    .from('remote_apply_sessions')
    .update({ status: 'expired', ended_at: deps.now().toISOString() })
    .eq('application_id', app.id)
    .eq('status', 'open')
    .lt('started_at', new Date(deps.now().getTime() - SESSION_SECONDS * 1000).toISOString())
    .select('provider, provider_session_id');
  for (const s of stale ?? []) {
    // try, not .catch: getProvider throws at once when that provider is no longer configured.
    try {
      if (s.provider_session_id) await deps.provider(s.provider).release(s.provider_session_id);
    } catch {
      // best effort: the provider's own timeout ends it anyway
    }
  }
  const { data: row, error: insertError } = await sb
    .from('remote_apply_sessions')
    .insert({ application_id: app.id, user_id: user.id, provider: provider.name })
    .select('id')
    .single();
  if (insertError || !row) {
    if (insertError?.code === '23505') throw new RemoteError(409, 'A fill session is already open for this application.');
    throw new RemoteError(500, 'Could not start a fill session.');
  }
  const finish = (status: SessionState, extra: Record<string, unknown> = {}) =>
    sb.from('remote_apply_sessions').update({ status, ended_at: deps.now().toISOString(), ...extra }).eq('id', row.id);

  let providerId: string | undefined;
  let browser: Browser | undefined;
  try {
    const created = await provider.create();
    providerId = created.id;
    const { error: saveError } = await sb.from('remote_apply_sessions').update({ provider_session_id: providerId }).eq('id', row.id);
    // Without the ID no later check could find or release this session, so stop here.
    if (saveError) throw new Error('could not save the provider session id');
    browser = await deps.connect(created.connection);
    const page = await firstPage(browser);
    const response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30_000 });
    if (response && (response.status() === 404 || response.status() === 410)) {
      await provider.release(providerId).catch(() => {});
      await finish('posting_gone');
      throw new RemoteError(410, 'This posting is no longer open.');
    }
    await page.locator('input, textarea, select').first().waitFor({ state: 'attached', timeout: 20_000 }).catch(() => {});
    const result = await deps.fill(page, plan, profile, cv);
    const captcha = await deps.captchaVisible(page);
    await sb
      .from('remote_apply_sessions')
      .update({ fields_planned: result.planned, fields_filled: result.filled, fields_unfilled: result.unfilled.length, captcha_seen: captcha })
      .eq('id', row.id);
    // Disconnect first: Cloudflare hands out the live view over a connection of its own.
    await browser.close().catch(() => {});
    browser = undefined;
    // One retry before giving up a form that is already filled; a 429 still ends in the quota message below.
    const id = providerId;
    const liveViewUrl = await provider.liveViewUrl(id).catch(() => provider.liveViewUrl(id));
    const remembered = new Map(result.remembered.map((r) => [r.label, r.similar]));
    const forUser = (plan?.for_user ?? []).flatMap((q) => {
      if (result.drafted.includes(q.label)) return [`${q.label} (draft typed in, please review)`];
      const similar = remembered.get(q.label);
      if (similar === undefined) return [q.label];
      return similar ? [`${q.label} (saved answer to a similar question, please check)`] : []; // exact: answered
    });
    return { sessionId: row.id, liveViewUrl, leftForUser: [...new Set([...forUser, ...result.unfilled])] };
  } catch (e) {
    if (e instanceof RemoteError) throw e;
    const quota = (e as { status?: number })?.status === 429; // a free plan's daily or monthly minutes are used up
    console.error('Remote fill failed:', quota ? 'quota' : errorName(e));
    if (providerId) await provider.release(providerId).catch(() => {});
    await finish('error', { error: quota ? 'quota' : errorName(e) });
    if (quota) throw new RemoteError(503, 'The remote browser service has no free time left today. Use the Apply link instead.');
    throw new RemoteError(502, 'The remote browser could not open this form. Use the Apply link instead.');
  } finally {
    await browser?.close().catch(() => {}); // disconnects; the provider keeps the session for the live view
  }
}

/**
 * Checks an open session: records Applied on the employer's confirmation page, closes it when the switch is off or
 * it is too old. With `final` (the user closed the view), an unconfirmed session is closed as abandoned.
 */
export async function checkSession(sb: SupabaseClient, sessionId: number, final = false): Promise<{ state: CheckState; captcha?: boolean }> {
  const { data: row } = await sb
    .from('remote_apply_sessions')
    .select('id, status, provider, provider_session_id, captcha_seen, started_at, application_id, applications!inner(job_postings!inner(companies!inner(ats_platform)))')
    .eq('id', sessionId)
    .single();
  if (!row) throw new RemoteError(404, 'Session not found.');
  if (row.status !== 'open') return { state: row.status };

  // The provider that made this session, even if REMOTE_APPLY_PROVIDER has changed since. If it is no longer
  // configured, nothing can reach the session: close the row so it does not stay open, and let the provider time out.
  let provider: RemoteProvider;
  try {
    provider = deps.provider(row.provider);
  } catch {
    await sb.from('remote_apply_sessions').update({ status: 'expired', ended_at: deps.now().toISOString() }).eq('id', row.id).eq('status', 'open');
    return { state: 'expired' };
  }
  const close = async (state: SessionState, extra: Record<string, unknown> = {}) => {
    if (row.provider_session_id) await provider.release(row.provider_session_id).catch(() => {});
    // Only an open row changes, so two tabs closing at once record one outcome.
    await sb
      .from('remote_apply_sessions')
      .update({ status: state, ended_at: deps.now().toISOString(), ...extra })
      .eq('id', row.id)
      .eq('status', 'open');
    return { state };
  };

  // Switched off or over age: still look for a confirmation once, then end it (a last-second submit still counts).
  const ending = !isEnabled() || deps.now().getTime() - new Date(row.started_at).getTime() > SESSION_SECONDS * 1000;
  const giveUp = () => close(final ? 'abandoned' : 'expired');
  let connection: Connection | null = null;
  if (row.provider_session_id) {
    try {
      connection = await provider.connection(row.provider_session_id);
    } catch {
      // A failed lookup (a 429, a network blip) is not an ended session; the next poll tries again.
      return final || ending ? giveUp() : { state: 'open' };
    }
  }
  if (!connection) return close('expired');

  const platform: string = (row.applications as any)?.job_postings?.companies?.ats_platform ?? '';
  let browser: Browser | undefined;
  try {
    browser = await deps.connect(connection);
    const page = await firstPage(browser);
    const body = (await page.locator('body').innerText({ timeout: 5_000 }).catch(() => '')).slice(0, 20_000);
    const captcha = row.captcha_seen || (await deps.captchaVisible(page));
    // Every application form has a CV upload; once it is gone, the form was sent.
    const formPresent = (await page.locator('input[type=file]').count().catch(() => 1)) > 0;
    if (isConfirmation(platform, page.url(), body, formPresent)) {
      // The same compare-and-set as Mark as Applied; if the user already marked it, nothing changes.
      const { error: markError } = await sb
        .from('applications')
        .update({ status: 'submitted' })
        .eq('id', row.application_id)
        .eq('status', 'manual_apply')
        .select('id');
      await close('submitted', { captcha_seen: captcha });
      return { state: markError ? 'unrecorded' : 'submitted' };
    }
    if (final || ending) return close(final ? 'abandoned' : 'expired', { captcha_seen: captcha });
    if (captcha && !row.captcha_seen) await sb.from('remote_apply_sessions').update({ captcha_seen: true }).eq('id', row.id);
    return { state: 'open', captcha };
  } catch (e) {
    console.error('Remote session check failed:', errorName(e));
    return final || ending ? giveUp() : { state: 'open' }; // a failed check is retried on the next poll
  } finally {
    await browser?.close().catch(() => {});
  }
}
