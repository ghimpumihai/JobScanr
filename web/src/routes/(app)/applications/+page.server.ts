import { fail } from '@sveltejs/kit';
import type { PageServerLoad, Actions } from './$types';
import type { ApplicationRecord } from '$lib/types';
import { isSupabaseConfigured } from '$lib/supabase/server';

const MOCK_APPLICATIONS: ApplicationRecord[] = [
  {
    id: 101,
    job_posting_id: 11,
    title: 'Junior Backend Engineer',
    company_name: 'Spotify',
    location: 'Stockholm / London',
    ats_platform: 'greenhouse',
    status: 'submitted',
    submitted_at: 'Oct 16, 06:14 UTC',
    attempt_token: 'gh_app_7a89f0'
  },
  {
    id: 102,
    job_posting_id: 12,
    title: 'Software Engineer 1',
    company_name: 'Revolut',
    location: 'London (Hybrid)',
    ats_platform: 'lever',
    status: 'needs_review',
    scheduled_at: 'Action Required',
    screening_question: 'Describe a complex backend or async issue you resolved.',
    drafted_answer:
      'During my internship at Acme Cloud, our daily ingestion workers faced 429 rate limit drops on GraphQL endpoints. I implemented serialized asyncio pacing locks, which restored 100% throughput without worker crash loops.',
    work_authorization: 'Authorized to work in UK & EU (No visa sponsorship required)'
  },
  {
    id: 103,
    job_posting_id: 13,
    title: 'Associate Systems Engineer',
    company_name: 'Cloudflare',
    location: 'London',
    ats_platform: 'greenhouse',
    status: 'queued',
    scheduled_at: 'Scheduled 08:00 UTC',
    attempt_token: 'tok_b9218d'
  }
];

export const load: PageServerLoad = async ({ locals }) => {
  const isLiveUser =
    locals.user && locals.supabase && isSupabaseConfigured() && locals.user.id !== 'demo-user-id';
  if (!isLiveUser) {
    return { applications: MOCK_APPLICATIONS, loadError: false };
  }

  // Real users never see mock rows: an empty list or an error must look like what it is.
  const { data, error } = await locals.supabase
    .from('applications')
    .select(`
      id, job_posting_id, status, attempt_token, attempts, created_at,
      job_postings ( title, location, companies ( name, ats_platform ) )
    `)
    .order('created_at', { ascending: false });

  if (error || !data) {
    console.error('Failed to load applications:', error?.message);
    return { applications: [] as ApplicationRecord[], loadError: true };
  }

  const applications: ApplicationRecord[] = data.map((row: any) => ({
    id: row.id,
    job_posting_id: row.job_posting_id,
    title: row.job_postings?.title ?? 'Unknown role',
    company_name: row.job_postings?.companies?.name ?? 'Unknown company',
    location: row.job_postings?.location || 'Remote EU',
    ats_platform: row.job_postings?.companies?.ats_platform ?? 'greenhouse',
    status: row.status,
    attempt_token: row.attempt_token,
    attempts: row.attempts,
    submitted_at: new Date(row.created_at).toUTCString()
  }));
  return { applications, loadError: false };
};

export const actions: Actions = {
  // There is no database function behind this yet (no `approve_application_review` RPC, no answer
  // column), so report that instead of claiming the application was queued.
  submitReview: async () => fail(501, { error: 'Approving reviewed applications is not available yet.' })
};
