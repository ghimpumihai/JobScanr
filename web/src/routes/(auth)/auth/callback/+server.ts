import { redirect } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = async ({ url, locals, cookies }) => {
  const code = url.searchParams.get('code');
  const next = url.searchParams.get('next') ?? '/matches';

  if (code && locals.supabase) {
    try {
      const { error } = await locals.supabase.auth.exchangeCodeForSession(code);
      if (!error) {
        cookies.delete('jobscanr_logged_out', { path: '/' });
        throw redirect(303, next);
      }
    } catch (e: any) {
      if (e?.status === 303) throw e;
      console.error('Failed to exchange code for session:', e?.message || e);
    }
  }

  throw redirect(303, '/login?error=Could not authenticate with email link. Please try again or enter the 6-digit code.');
};
