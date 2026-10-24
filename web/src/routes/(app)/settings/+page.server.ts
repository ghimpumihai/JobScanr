import type { PageServerLoad, Actions } from './$types';
import type { UserProfile } from '$lib/types';
import { isSupabaseConfigured } from '$lib/supabase/server';

const MOCK_PROFILE: UserProfile = {
  id: 1,
  email: 'stefan@example.com',
  full_name: 'Stefan Ghimpu',
  resume_filename: 'stefan_ghimpu_cv_2026.pdf',
  resume_size_kb: 142,
  resume_uploaded_at: 'Oct 12, 2026',
  seniority_levels: ['Graduate / New Grad', 'Entry Level (0-1 yrs)', 'Junior (1-2 yrs)'],
  preferred_locations: ['London', 'Berlin', 'Amsterdam', 'Dublin', 'Paris', 'Remote EU'],
  target_keywords: ['Backend', 'Python', 'Go', 'Distributed Systems', 'Platform'],
  excluded_keywords: ['Senior', 'Lead', 'Principal', 'Staff', 'Clearance', 'C++'],
  work_authorization: 'Authorized to work in UK & EU (No visa sponsorship required)',
  auto_apply_mode: 'approval_required',
  max_daily_applications: 10,
  max_apps_per_company: 2
};

export const load: PageServerLoad = async ({ locals }) => {
  if (locals.user && locals.supabase && isSupabaseConfigured() && locals.user.id !== 'demo-user-id') {
    try {
      const { data, error } = await locals.supabase
        .from('users')
        .select('*')
        .eq('auth_user_id', locals.user.id)
        .single();

      if (!error && data) {
        const liveProfile: UserProfile = {
          id: data.id,
          email: data.email,
          full_name: data.screening_defaults?.full_name || 'Stefan Ghimpu',
          resume_filename: data.resume_filename || 'stefan_ghimpu_cv_2026.pdf',
          resume_storage_path: data.resume_storage_path,
          resume_content_type: data.resume_content_type,
          resume_uploaded_at: data.resume_uploaded_at ? new Date(data.resume_uploaded_at).toLocaleDateString() : 'Oct 12, 2026',
          resume_size_kb: 142,
          seniority_levels: data.profile_filters?.levels || MOCK_PROFILE.seniority_levels,
          preferred_locations: data.profile_filters?.locations || MOCK_PROFILE.preferred_locations,
          target_keywords: data.profile_filters?.target_title_keywords || MOCK_PROFILE.target_keywords,
          excluded_keywords: data.profile_filters?.excluded_title_keywords || MOCK_PROFILE.excluded_keywords,
          work_authorization: data.screening_defaults?.work_authorization || MOCK_PROFILE.work_authorization,
          auto_apply_mode: data.auto_apply_mode || 'approval_required',
          max_daily_applications: data.max_daily_applications || 10,
          max_apps_per_company: data.max_apps_per_company || 2
        };
        return { profile: liveProfile };
      }
    } catch {
      // Fallback to mock profile
    }
  }

  return {
    profile: MOCK_PROFILE
  };
};

export const actions: Actions = {
  savePreferences: async ({ request, locals }) => {
    const formData = await request.formData();
    const fullName = formData.get('fullName');
    const workAuth = formData.get('workAuth');

    if (locals.user && locals.supabase) {
      try {
        const { data: existingUser } = await locals.supabase
          .from('users')
          .select('screening_defaults, profile_filters')
          .eq('auth_user_id', locals.user.id)
          .single();

        const currentDefaults = existingUser?.screening_defaults || {};

        const updatedDefaults = {
          ...currentDefaults,
          ...(fullName ? { full_name: fullName.toString() } : {}),
          ...(workAuth ? { work_authorization: workAuth.toString() } : {})
        };

        await locals.supabase
          .from('users')
          .update({
            screening_defaults: updatedDefaults
          })
          .eq('auth_user_id', locals.user.id);
      } catch {
        // Log error
      }
    }

    return { success: true, message: "Preferences saved. Active for tomorrow's 06:00 UTC scan." };
  }
};
