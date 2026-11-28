import { fail, redirect, type Actions } from '@sveltejs/kit';
import { isSupabaseConfigured } from '$lib/supabase/server';

export const actions: Actions = {
  logout: async ({ locals, cookies }) => {
    if (locals.supabase && isSupabaseConfigured()) {
      try {
        await locals.supabase.auth.signOut();
      } catch (e) {}
    }
    cookies.delete('jobscanr_demo_session', { path: '/' });
    cookies.set('jobscanr_logged_out', 'true', {
      path: '/',
      httpOnly: true,
      sameSite: 'lax',
      maxAge: 60 * 60 * 24 * 7
    });
    throw redirect(303, '/login');
  },

  demoLogin: async ({ cookies }) => {
    cookies.delete('jobscanr_logged_out', { path: '/' });
    cookies.set('jobscanr_demo_session', 'true', {
      path: '/',
      httpOnly: true,
      sameSite: 'lax',
      maxAge: 60 * 60 * 24 * 7
    });
    throw redirect(303, '/inbox');
  },

  google: async ({ locals, cookies, url }) => {
    // No silent demo fallback: a missing config must be visible, or the user ends up in demo data unknowingly.
    if (!isSupabaseConfigured()) {
      return fail(503, { error: 'Supabase is not configured: SUPABASE_ANON_KEY and SUPABASE_URL (or DATABASE_URL) are not set.' });
    }
    cookies.delete('jobscanr_logged_out', { path: '/' });
    // PKCE: the code verifier is stored in a cookie here and used by /auth/callback's exchangeCodeForSession.
    const { data, error } = await locals.supabase.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: `${url.origin}/auth/callback?next=/inbox` }
    });
    if (error || !data.url) {
      return fail(500, { error: `Google sign-in could not start: ${error?.message ?? 'no redirect URL'}` });
    }
    throw redirect(303, data.url);
  }
};
