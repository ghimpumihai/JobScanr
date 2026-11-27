// Redraft with a note (#142): during a live Fill it for me session, the user adds a fact or a steer to one drafted
// answer; Groq writes a new draft with the same prompt as the pipeline's drafts (jobs/apply/draft_prompt.json), and
// it is typed into that one field. The note is fenced as data and never stored; equal-opportunity answers and the
// profile are never sent. The user still reviews the answer and clicks Submit (constitution 1.5).
import type { SupabaseClient } from '@supabase/supabase-js';
import { fetchDescription } from '../description';
import PROMPT from '../../../../../jobs/apply/draft_prompt.json';
import { typeAnswer, type FillPlan } from './fill';
import { SESSION_SECONDS } from './provider';
import { deps, firstPage, isAllowlisted, isEnabled, RemoteError } from './session';

export const PER_QUESTION = 3;
export const PER_SESSION = 10; // with DAILY_CAP sessions, at most 50 Groq calls per user per day
export const MAX_NOTE = 500;
// The same limits as jobs/apply/llm_answers.py.
const MAX_CV_CHARS = 8000;
const MIN_CV_CHARS = 200;
const MAX_JD_CHARS = 4000;
const MAX_WORDS = 150;
const MAX_CHARS = 1000;
const GROQ_URL = 'https://api.groq.com/openai/v1/chat/completions';

/** Swapped in tests; nothing else changes them. */
export const redraftDeps = {
  fetch: (url: string, init?: RequestInit): Promise<Response> => fetch(url, init),
  cvText,
  typeAnswer
};

// shortcut: counts live in this server's memory, so a restart resets them and each server instance has its own;
// move them to a column of remote_apply_sessions the user cannot write if the trial grows beyond a few users.
const counts = new Map<number, { total: number; byQuestion: Map<string, number>; until: number }>();

/** Plain text of a PDF CV, as llm_answers.extract_cv_text gives it, or null. */
async function cvText(cv: { name: string; buffer: Buffer }): Promise<string | null> {
  if (!cv.name.toLowerCase().endsWith('.pdf')) return null; // shortcut: DOCX CVs are not read here yet
  // shortcut: needs `npm install unpdf` in web/ (no PDF reader is installed, and installing needs the network). Until
  // then this returns null and Redraft says it cannot read the CV. Make it a static import once installed.
  const lib = 'unpdf';
  try {
    const { extractText, getDocumentProxy } = await import(/* @vite-ignore */ lib);
    const pdf = await getDocumentProxy(new Uint8Array(cv.buffer));
    const { text } = await extractText(pdf, { mergePages: false });
    const lines = (text as string[]).slice(0, 5).join('\n').split('\n').map((l) => l.split(/\s+/).filter(Boolean).join(' '));
    const joined = lines.filter(Boolean).join('\n');
    return joined.length >= MIN_CV_CHARS ? joined.slice(0, MAX_CV_CHARS) : null;
  } catch {
    return null;
  }
}

/** Fills {name} placeholders in one pass, so text put in is never read as a placeholder. */
const fillIn = (lines: string[], values: Record<string, string>) =>
  lines.join('\n').replace(/\{(\w+)\}/g, (m, key: string) => values[key] ?? m);

/** The chat messages for a redraft. The note's angle brackets are dropped, so it cannot close its own tag. */
export function redraftMessages(question: string, jobDescription: string, cv: string, note: string) {
  const fenced = note.replace(/[<>]/g, '').trim();
  return [
    { role: 'system', content: fillIn(PROMPT.system, { max_words: String(MAX_WORDS) }) },
    {
      role: 'user',
      content: fillIn(PROMPT.user, {
        cv: cv.slice(0, MAX_CV_CHARS),
        job_description: jobDescription.slice(0, MAX_JD_CHARS),
        question,
        note: fenced ? fillIn(PROMPT.note, { note: fenced }) : ''
      })
    }
  ];
}

/** truncate_answer in jobs/apply/llm_answers.py: cut at the last sentence end inside the limits, else a whole word. */
function truncate(raw: string): string {
  const text = raw.split(/\s+/).filter(Boolean).join(' ');
  const limit = Math.min(text.split(' ').slice(0, MAX_WORDS).join(' ').length, MAX_CHARS);
  if (text.length <= limit) return text;
  const ends = [...text.matchAll(/[.!?](?=\s|$)/g)].map((m) => m.index + 1).filter((end) => end <= limit);
  if (ends.length) return text.slice(0, ends.at(-1));
  const space = text.lastIndexOf(' ', limit);
  return space > 0 ? text.slice(0, space) : text.slice(0, limit);
}

/** The posting's description as plain text, from the same live fetch as the role panel; '' when it cannot be read. */
async function jobDescription(platform: string, ident: string, externalId: string): Promise<string> {
  try {
    const d = await fetchDescription(platform, ident, externalId, redraftDeps.fetch as typeof fetch);
    return (d?.blocks ?? []).map((b) => ('h' in b ? b.h : 'p' in b ? b.p : b.li.join('\n'))).join('\n');
  } catch {
    return '';
  }
}

async function groq(messages: { role: string; content: string }[]): Promise<string> {
  const apiKey = process.env.GROQ_API_KEY;
  if (!apiKey) throw new RemoteError(503, 'Redraft is not set up on this server.');
  const model = process.env.GROQ_MODEL || 'openai/gpt-oss-120b';
  let res: Response;
  try {
    res = await redraftDeps.fetch(GROQ_URL, {
      method: 'POST',
      headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
      // The same request as llm_answers.draft_open_question_answer: gpt-oss needs low effort to leave room to answer.
      body: JSON.stringify({ model, temperature: 0.3, max_tokens: 1000, ...(model.startsWith('openai/gpt-oss') ? { reasoning_effort: 'low' } : {}), messages }),
      signal: AbortSignal.timeout(20_000)
    });
  } catch {
    throw new RemoteError(502, 'Could not reach the drafting service. Try again.');
  }
  if (res.status === 429) throw new RemoteError(429, 'The drafting service is busy. Try again in a minute.');
  const content = res.ok ? (await res.json().catch(() => null))?.choices?.[0]?.message?.content : null;
  if (typeof content !== 'string') throw new RemoteError(502, 'The drafting service did not answer. Try again.');
  return content;
}

export async function redraft(
  sb: SupabaseClient,
  authUserId: string,
  sessionId: number,
  label: string,
  note: string
): Promise<{ draft: string; leftForUser: string[] }> {
  if (!isEnabled()) throw new RemoteError(503, 'Fill it for me is switched off.');
  if (!label || label.length > 500) throw new RemoteError(400, 'Unknown question.');
  if (note.length > MAX_NOTE) throw new RemoteError(400, `Keep the note to ${MAX_NOTE} characters.`);

  const { data: user } = await sb
    .from('users')
    .select('id, resume_storage_path, resume_filename, llm_drafts_enabled')
    .eq('auth_user_id', authUserId)
    .single();
  if (!user) throw new RemoteError(500, 'Could not load your profile.');
  if (!isAllowlisted(user.id)) throw new RemoteError(403, 'Fill it for me is only open to the trial group.');
  if (!user.llm_drafts_enabled) throw new RemoteError(403, 'Turn on drafted answers in Settings first.');

  const { data: row } = await sb
    .from('remote_apply_sessions')
    .select('id, user_id, status, provider, provider_session_id, started_at, application_id, applications!inner(job_postings!inner(external_id, companies!inner(ats_platform, ats_identifier)))')
    .eq('id', sessionId)
    .single();
  if (!row || row.user_id !== user.id) throw new RemoteError(404, 'Session not found.');
  const tooOld = deps.now().getTime() - new Date(row.started_at).getTime() > SESSION_SECONDS * 1000;
  if (row.status !== 'open' || tooOld || !row.provider_session_id) throw new RemoteError(409, 'This fill session has ended.');

  const { data: planRow } = await sb.from('application_fill_plans').select('plan').eq('application_id', row.application_id).maybeSingle();
  // Only the open-ended questions the pipeline drafts: never a fact, equal-opportunity or saved-answer field.
  const entry = (planRow?.plan as FillPlan | undefined)?.for_user?.find((q) => q.label === label && q.reason === 'open_ended');
  if (!entry) throw new RemoteError(404, 'Only drafted questions can be redrafted.');

  const now = deps.now().getTime();
  for (const [id, c] of counts) if (c.until < now) counts.delete(id);
  const count = counts.get(row.id) ?? { total: 0, byQuestion: new Map<string, number>(), until: now + SESSION_SECONDS * 1000 };
  if (count.total >= PER_SESSION) throw new RemoteError(429, `You can redraft ${PER_SESSION} times per form.`);
  if ((count.byQuestion.get(label) ?? 0) >= PER_QUESTION) throw new RemoteError(429, `You can redraft each answer ${PER_QUESTION} times.`);

  if (!user.resume_storage_path) throw new RemoteError(422, 'Upload a CV in Settings first.');
  const { data: blob } = await sb.storage.from('resumes').download(user.resume_storage_path);
  if (!blob) throw new RemoteError(502, 'Could not read your CV.');
  const cv = await redraftDeps.cvText({ name: user.resume_filename ?? user.resume_storage_path, buffer: Buffer.from(await blob.arrayBuffer()) });
  if (!cv) throw new RemoteError(422, 'JobScanr cannot read the text of your CV, so it cannot redraft this answer.');

  const posting: any = (row.applications as any)?.job_postings; // nested join rows are untyped
  const jd = await jobDescription(posting?.companies?.ats_platform ?? '', posting?.companies?.ats_identifier ?? '', String(posting?.external_id ?? ''));
  const content = await groq(redraftMessages(label, jd, cv, note));
  count.total += 1;
  count.byQuestion.set(label, (count.byQuestion.get(label) ?? 0) + 1);
  counts.set(row.id, count);
  if (content.replace(/^["'`*.!\s]+|["'`*.!\s]+$/g, '').toUpperCase() === 'SKIP') {
    throw new RemoteError(422, 'Only you can answer this one. Type it in the form.');
  }
  const draft = truncate(content);
  if (!draft) throw new RemoteError(502, 'The drafting service did not answer. Try again.');

  const connection = await deps
    .provider(row.provider)
    .connection(row.provider_session_id)
    .catch(() => null);
  if (!connection) throw new RemoteError(409, 'This fill session has ended.');
  const browser = await deps.connect(connection);
  try {
    const leftForUser = await redraftDeps.typeAnswer(await firstPage(browser), entry.name, draft);
    if (!leftForUser) throw new RemoteError(409, 'That question is no longer on the form.');
    return { draft, leftForUser };
  } finally {
    await browser.close().catch(() => {}); // disconnects; the live view keeps the session
  }
}
