import { fail, redirect, type Actions } from '@sveltejs/kit';

export const actions: Actions = {
  sendOtp: async ({ request, locals }) => {
    const formData = await request.formData();
    const email = formData.get('email')?.toString().trim();

    if (!email) {
      return fail(400, { error: 'Please enter a valid email address.' });
    }

    const { error } = await locals.supabase.auth.signInWithOtp({
      email,
      options: {
        emailRedirectTo: '/matches'
      }
    });

    if (error) {
      return fail(500, { error: error.message });
    }

    return { success: true, email };
  },

  verifyOtp: async ({ request, locals }) => {
    const formData = await request.formData();
    const email = formData.get('email')?.toString().trim();
    const token = formData.get('token')?.toString().trim();

    if (!email || !token) {
      return fail(400, { error: 'Both email and verification code are required.' });
    }

    const { error } = await locals.supabase.auth.verifyOtp({
      email,
      token,
      type: 'email'
    });

    if (error) {
      return fail(400, { error: error.message });
    }

    throw redirect(303, '/matches');
  }
};
