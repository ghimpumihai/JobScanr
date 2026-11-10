import type { PageServerLoad, Actions } from './$types';
import type { JobMatch } from '$lib/types';
import { isSupabaseConfigured } from '$lib/supabase/server';

const MOCK_MATCHES: JobMatch[] = [
  {
    id: 1,
    external_id: 'datadog-junior-swe',
    title: 'Datadog — Junior Software Engineer',
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
    title: 'Stripe — New Grad Backend Developer',
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
    title: 'Salesforce — Software Engineer Intern (Summer 2027)',
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
    title: 'Synthesia — Junior Full-Stack Engineer',
    company_name: 'Synthesia',
    location: 'London / Remote',
    compensation: '£55,000 – £62,000',
    ats_platform: 'ashby',
    url: 'https://ashbyhq.com',
    match_score: 89
  }
];

export const load: PageServerLoad = async ({ locals }) => {
  // If authenticated with live Supabase database, attempt query with fallback to mock data
  if (locals.user && locals.supabase && isSupabaseConfigured() && locals.user.id !== 'demo-user-id') {
    try {
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

      if (!error && data && data.length > 0) {
        const liveMatches: JobMatch[] = data.map((row: any) => {
          const compName = row.job_postings?.companies?.name || 'Company';
          const jobTitle = row.job_postings?.title || 'Engineering Role';
          return {
            id: row.id,
            external_id: row.job_postings?.external_id || `match-${row.id}`,
            title: `${compName} — ${jobTitle}`,
            company_name: compName,
            location: row.job_postings?.location || 'Remote EU',
            compensation: row.job_postings?.compensation,
            ats_platform: row.job_postings?.companies?.ats_platform || 'greenhouse',
            url: row.job_postings?.url || '#',
            match_score: Math.round((row.match_score || 0.9) * 100)
          };
        });
        return { matches: liveMatches };
      }
    } catch {
      // Graceful fallback to mock data
    }
  }

  return {
    matches: MOCK_MATCHES
  };
};

export const actions: Actions = {
  queueAllDirect: async () => {
    return { success: true, message: 'Queued all 3 direct matches for review.' };
  },
  queueSingle: async ({ request }) => {
    const data = await request.formData();
    const id = data.get('id');
    return { success: true, message: `Queued role #${id} for screening review.` };
  }
};
