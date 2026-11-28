import { redirect } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';
import { isSupabaseConfigured } from '$lib/supabase/server';
import { safeHttpUrl } from '$lib/safeUrl';

// The Fill it for me page (#141). Its session actions (remoteStart, remotePoll, remoteEnd, remoteRedraft) are the
// Inbox's, so the checks stay in one place; this load only names the role for the page header.
export const load: PageServerLoad = async ({ locals, url }) => {
  const idRaw = url.searchParams.get('role') ?? '';
  if (!/^\d{1,15}$/.test(idRaw)) redirect(303, '/inbox');
  const id = Number(idRaw);
  const live = locals.user && locals.supabase && isSupabaseConfigured() && locals.user.id !== 'demo-user-id';
  if (!live) {
    return { role: { id, title: 'Demo role', company_name: 'Demo company', location: '', ats_platform: 'greenhouse', url: '#' }, demo: true };
  }
  const { data } = await locals.supabase
    .from('applications')
    .select('id, job_postings!inner(title, location, url, companies!inner(name, ats_platform))')
    .eq('id', id)
    .maybeSingle();
  const posting: any = data?.job_postings; // nested join rows are untyped
  if (!posting) redirect(303, '/inbox');
  return {
    role: {
      id,
      title: posting.title ?? 'Unknown role',
      company_name: posting.companies?.name ?? 'Unknown company',
      location: posting.location ?? '',
      ats_platform: posting.companies?.ats_platform ?? '',
      url: safeHttpUrl(posting.url)
    },
    demo: false
  };
};
