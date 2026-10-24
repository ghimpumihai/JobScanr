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
    throw redirect(303, '/matches');
  },

  sendOtp: async ({ request, locals, cookies, url }) => {
    cookies.delete('jobscanr_logged_out', { path: '/' });
    const formData = await request.formData();
    const email = formData.get('email')?.toString().trim();

    if (!email) {
      return fail(400, { error: 'Please enter a valid email address.' });
    }

    if (!isSupabaseConfigured()) {
      // Local prototype mode without live Supabase credentials
      return { success: true, email, isMock: true };
    }

    try {
      const { error } = await locals.supabase.auth.signInWithOtp({
        email,
        options: {
          emailRedirectTo: `${url.origin}/auth/callback?next=/matches`
        }
      });

      if (error) {
        return fail(500, { error: error.message, email });
      }
    } catch (err: any) {
      return fail(500, {
        error: `Supabase connection failed: ${err.message}. Configure SUPABASE_URL & SUPABASE_ANON_KEY in your .env or click Demo Mode.`,
        email
      });
    }

    return { success: true, email };
  },

  verifyOtp: async ({ request, locals, cookies }) => {
    cookies.delete('jobscanr_logged_out', { path: '/' });
    const formData = await request.formData();
    const email = formData.get('email')?.toString().trim();
    const token = formData.get('token')?.toString().trim();

    if (!email || !token) {
      return fail(400, { error: 'Both email and verification code are required.', email });
    }

    if (!isSupabaseConfigured()) {
      // Allow 123456 or any 6-digit code in local prototype mode
      if (token === '123456' || token.length === 6) {
        cookies.set('jobscanr_demo_session', 'true', {
          path: '/',
          httpOnly: true,
          sameSite: 'lax',
          maxAge: 60 * 60 * 24 * 7
        });
        throw redirect(303, '/matches');
      }
      return fail(400, { error: 'Prototype code is 123456.', email });
    }

    try {
      let verifyResult = await locals.supabase.auth.verifyOtp({
        email,
        token,
        type: 'email'
      });

      if (verifyResult.error) {
        // If the email was a new signup or email confirmation token, retry with type: 'signup'
        const signupResult = await locals.supabase.auth.verifyOtp({
          email,
          token,
          type: 'signup'
        });
        if (!signupResult.error) {
          verifyResult = signupResult;
        }
      }

      if (verifyResult.error) {
        return fail(400, { error: verifyResult.error.message, email });
      }
    } catch (err: any) {
      if (err?.status === 303) throw err;
      return fail(500, { error: `Supabase verify failed: ${err.message}`, email });
    }

    throw redirect(303, '/matches');
  }
};
