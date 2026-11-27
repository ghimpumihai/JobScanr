import { error, json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { isSupabaseConfigured } from '$lib/supabase/server';
import { fetchDescription, type Description } from '$lib/server/description';

// Demo text only; real roles always come from the employer's board.
const DEMO: Description = {
  facts: [
    { k: 'Type', v: 'Full-time' },
    { k: 'Workplace', v: 'Hybrid' }
  ],
  blocks: [
    { p: 'Demo description: in your own account this is read live from the employer’s job board when you open a role.' },
    { h: 'What you will do' },
    { li: ['Build and maintain backend services', 'Write tests and take part in code review'] }
  ]
};

/** The open role's description, read live from its job board (#141). Never stored (constitution 1.3). */
export const GET: RequestHandler = async ({ locals, url }) => {
  const idRaw = url.searchParams.get('id') ?? '';
  if (!/^\d{1,15}$/.test(idRaw)) error(400, 'Unknown role.');
  const live = locals.user && locals.supabase && isSupabaseConfigured() && locals.user.id !== 'demo-user-id';
  if (!live) return json(DEMO);

  // Row-level security limits this to the user's own applications.
  const { data } = await locals.supabase
    .from('applications')
    .select('id, job_postings!inner(external_id, companies!inner(ats_platform, ats_identifier))')
    .eq('id', Number(idRaw))
    .maybeSingle();
  const posting: any = data?.job_postings; // nested join rows are untyped
  if (!posting) error(404, 'Unknown role.');

  let description: Description | null = null;
  try {
    description = await fetchDescription(posting.companies?.ats_platform ?? '', posting.companies?.ats_identifier ?? '', String(posting.external_id ?? ''));
  } catch (e) {
    console.error('Description fetch failed:', e instanceof Error ? e.message : 'Error');
  }
  if (!description?.blocks.length) error(502, 'Could not load the description.');
  return json(description, { headers: { 'cache-control': 'private, max-age=3600' } });
};
