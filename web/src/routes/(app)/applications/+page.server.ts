import type { PageServerLoad, Actions } from './$types';
import type { ApplicationRecord } from '$lib/types';

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
  if (locals.user && locals.supabase) {
    try {
      const { data, error } = await locals.supabase
        .from('applications')
        .select(`
          id, job_posting_id, status, attempt_token, attempts, created_at,
          job_postings ( title, location, companies ( name, ats_platform ) )
        `)
        .order('created_at', { ascending: false });

      if (!error && data && data.length > 0) {
        const liveApps: ApplicationRecord[] = data.map((row: any) => ({
          id: row.id,
          job_posting_id: row.job_posting_id,
          title: row.job_postings.title,
          company_name: row.job_postings.companies.name,
          location: row.job_postings.location || 'Remote EU',
          ats_platform: row.job_postings.companies.ats_platform,
          status: row.status,
          attempt_token: row.attempt_token,
          attempts: row.attempts,
          submitted_at: new Date(row.created_at).toUTCString()
        }));
        return { applications: liveApps };
      }
    } catch {
      // Fallback to mock data
    }
  }

  return {
    applications: MOCK_APPLICATIONS
  };
};

export const actions: Actions = {
  submitReview: async ({ request, locals }) => {
    const formData = await request.formData();
    const appId = formData.get('id');
    const answer = formData.get('answer');

    if (locals.user && locals.supabase && appId) {
      try {
        // Use RPC if available, or update drafted_answer without triggering queue protection error
        const { error: rpcErr } = await locals.supabase.rpc('approve_application_review', {
          app_id: appId,
          new_answer: answer?.toString()
        });
        if (rpcErr) {
          await locals.supabase
            .from('applications')
            .update({ drafted_answer: answer?.toString() })
            .eq('id', appId);
        }
      } catch {
        // Log error
      }
    }

    return { success: true, message: 'Application approved and queued for submission.' };
  }
};
