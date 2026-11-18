import { fail } from '@sveltejs/kit';
import type { PageServerLoad, Actions } from './$types';
import type { JobMatch } from '$lib/types';
import { isSupabaseConfigured } from '$lib/supabase/server';
import { safeHttpUrl } from '$lib/safeUrl';

const MOCK_MATCHES: JobMatch[] = [
  {
    id: 1,
    external_id: 'datadog-junior-swe',
    title: 'Junior Software Engineer',
    company_name: 'Datadog',
    location: 'Paris / London (Hybrid)',
    compensation: '€65,000 – €75,000',
    ats_platform: 'greenhouse',
    url: 'https://boards.greenhouse.io',
    match_score: 96
  },
  {
    id: 2,
    external_id: 'stripe-new-grad',
    title: 'New Grad Backend Developer',
    company_name: 'Stripe',
    location: 'Dublin / Remote EU',
    compensation: '€78,000',
    ats_platform: 'lever',
    url: 'https://jobs.lever.co',
    match_score: 94
  },
  {
    id: 3,
    external_id: 'salesforce-intern-2027',
    title: 'Software Engineer Intern (Summer 2027)',
    company_name: 'Salesforce',
    location: 'London, UK',
    compensation: '£45,000 pro-rata',
    ats_platform: 'workday',
    url: 'https://salesforce.wd12.myworkdayjobs.com',
    match_score: 91
  },
  {
    id: 4,
    external_id: 'synthesia-junior-fullstack',
    title: 'Junior Full-Stack Engineer',
    company_name: 'Synthesia',
    location: 'London / Remote',
    compensation: '£55,000 – £62,000',
    ats_platform: 'ashby',
    url: 'https://ashbyhq.com',
    match_score: 89
  }
];

export const load: PageServerLoad = async ({ locals }) => {
  const isLiveUser =
    locals.user && locals.supabase && isSupabaseConfigured() && locals.user.id !== 'demo-user-id';
  if (!isLiveUser) {
    return { matches: MOCK_MATCHES, loadError: false };
  }

  // Real users never see mock rows: an empty list or an error must look like what it is.
  const { data, error } = await locals.supabase
    .from('user_job_matches')
    .select(`
      id,
      match_score,
      job_postings (
        id, external_id, title, location, compensation, url,
        companies ( name, ats_platform )
      )
    `)
    .order('match_score', { ascending: false });

  if (error || !data) {
    console.error('Failed to load matches:', error?.message);
    return { matches: [] as JobMatch[], loadError: true };
  }

  const matches: JobMatch[] = data.map((row: any) => {
    const compName = row.job_postings?.companies?.name || 'Company';
    const jobTitle = row.job_postings?.title || 'Engineering Role';
    return {
      id: row.id,
      external_id: row.job_postings?.external_id || `match-${row.id}`,
      title: jobTitle,
      company_name: compName,
      location: row.job_postings?.location || 'Remote EU',
      compensation: row.job_postings?.compensation,
      ats_platform: row.job_postings?.companies?.ats_platform || 'greenhouse',
      url: safeHttpUrl(row.job_postings?.url),
      // match_score is 0..1 in the database; 0 is a real score, not "missing".
      match_score: Math.round((row.match_score ?? 0) * 100)
    };
  });
  return { matches, loadError: false };
};

export const actions: Actions = {
  // Applications can only be created by the backend today (users have no INSERT policy),
  // so these must not report success.
  queueAllDirect: async () => fail(501, { error: 'Queueing from the web is not available yet.' }),
  queueSingle: async () => fail(501, { error: 'Queueing from the web is not available yet.' })
};
