import { fail } from '@sveltejs/kit';
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
  work_authorization: 'yes',
  auto_apply_mode: 'approval_required',
  max_daily_applications: 10,
  max_apps_per_company: 2
};

// UI labels -> title words the Python matcher (jobs/match.py `levels`) looks for in a job title.
// Saving the labels themselves would never match a real title, so users would get zero matches.
// Keep keys identical to ALL_SENIORITY_LEVELS in settings/+page.svelte (tests/test_web_scaffold.py checks).
const LEVEL_TOKENS: Record<string, string[]> = {
  'Internship / Working Student': ['intern', 'internship', 'working student'],
  'Graduate / New Grad': ['graduate', 'new grad', 'new-grad'],
  'Entry Level (0-1 yrs)': ['entry level', 'entry-level', 'trainee', 'apprentice'],
  'Junior (1-2 yrs)': ['junior'],
  'Associate (2-3 yrs)': ['associate'],
  'Mid-Level (3-5 yrs)': ['mid-level', 'mid level'],
  'Senior (5-8 yrs)': ['senior'],
  'Lead / Principal (8+ yrs)': ['lead', 'principal', 'staff']
};

const MAX_LIST_ITEMS = 50;
const MAX_ITEM_LENGTH = 60;
const MAX_NAME_LENGTH = 120;

/** undefined = field absent (leave stored value alone), null = present but invalid. */
function parseList(raw: FormDataEntryValue | null): string[] | undefined | null {
  if (!raw) return undefined;
  try {
    const value = JSON.parse(raw.toString());
    if (
      Array.isArray(value) &&
      value.length <= MAX_LIST_ITEMS &&
      value.every((s) => typeof s === 'string' && s.trim() && s.length <= MAX_ITEM_LENGTH)
    ) {
      return value.map((s: string) => s.trim());
    }
  } catch {
    // fall through to invalid
  }
  return null;
}

export const load: PageServerLoad = async ({ locals }) => {
  const isLiveUser =
    locals.user && locals.supabase && isSupabaseConfigured() && locals.user.id !== 'demo-user-id';

  if (isLiveUser) {
    const { data, error } = await locals.supabase
      .from('users')
      .select('*')
      .eq('auth_user_id', locals.user!.id)
      .single();

    if (error || !data) {
      console.error('Failed to load user profile:', error?.message);
      return { profile: null, loadError: true };
    }

    const wa = data.screening_defaults?.work_authorization;
    const liveProfile: UserProfile = {
      id: data.id,
      email: data.email,
      full_name: data.screening_defaults?.full_name ?? '',
      resume_filename: data.resume_filename ?? undefined,
      resume_storage_path: data.resume_storage_path,
      resume_content_type: data.resume_content_type,
      resume_uploaded_at: data.resume_uploaded_at ? new Date(data.resume_uploaded_at).toLocaleDateString() : undefined,
      seniority_levels: Object.keys(LEVEL_TOKENS).filter((label) =>
        LEVEL_TOKENS[label].some((t) => (data.profile_filters?.levels ?? []).includes(t))
      ),
      preferred_locations: data.profile_filters?.locations ?? [],
      // The matcher reads `titles`; this is the same list.
      target_keywords: data.profile_filters?.titles ?? [],
      excluded_keywords: data.profile_filters?.excluded_title_keywords ?? [],
      work_authorization: wa === true ? 'yes' : wa === false ? 'no' : '',
      auto_apply_mode: data.auto_apply_mode || 'approval_required',
      max_daily_applications: data.max_daily_applications ?? 10,
      max_apps_per_company: data.max_apps_per_company ?? 2
    };
    return { profile: liveProfile, loadError: false };
  }

  return { profile: MOCK_PROFILE, loadError: false };
};

export const actions: Actions = {
  savePreferences: async ({ request, locals }) => {
    const formData = await request.formData();
    const fullName = formData.get('fullName')?.toString().trim();
    const workAuth = formData.get('workAuth')?.toString();

    const levelLabels = parseList(formData.get('seniorityLevels'));
    if (levelLabels && !levelLabels.every((l) => l in LEVEL_TOKENS)) {
      return fail(400, { error: 'Unknown seniority level.' });
    }
    const lists = {
      levels: levelLabels && [...new Set(levelLabels.flatMap((l) => LEVEL_TOKENS[l]))],
      locations: parseList(formData.get('locations')),
      titles: parseList(formData.get('targetKeywords')),
      excluded_title_keywords: parseList(formData.get('excludedKeywords'))
    };

    if (levelLabels === null || Object.values(lists).some((v) => v === null)) {
      return fail(400, { error: 'Invalid list value. Use short text items only (max 50 items, 60 characters each).' });
    }
    if (fullName && fullName.length > MAX_NAME_LENGTH) {
      return fail(400, { error: 'Name is too long.' });
    }
    if (workAuth && workAuth !== 'yes' && workAuth !== 'no') {
      return fail(400, { error: 'Work authorization must be Yes or No.' });
    }

    const isLiveUser =
      locals.user && locals.supabase && isSupabaseConfigured() && locals.user.id !== 'demo-user-id';
    if (!isLiveUser) {
      // Demo / unconfigured prototype mode: nothing is persisted.
      return { success: true, message: 'Demo mode: preferences are not stored.' };
    }

    const { data: existingUser, error: readError } = await locals.supabase
      .from('users')
      .select('screening_defaults, profile_filters')
      .eq('auth_user_id', locals.user!.id)
      .single();
    if (readError || !existingUser) {
      console.error('Failed to read user preferences:', readError?.message);
      return fail(500, { error: 'Could not load your current preferences. Nothing was saved.' });
    }

    const screening_defaults = {
      ...(existingUser.screening_defaults ?? {}),
      ...(fullName ? { full_name: fullName } : {}),
      // The apply worker expects a real boolean here, never free text.
      ...(workAuth ? { work_authorization: workAuth === 'yes' } : {})
    };
    const profile_filters = {
      ...(existingUser.profile_filters ?? {}),
      ...Object.fromEntries(Object.entries(lists).filter(([, v]) => v !== undefined))
    };

    const { error: writeError } = await locals.supabase
      .from('users')
      .update({ screening_defaults, profile_filters })
      .eq('auth_user_id', locals.user!.id);
    if (writeError) {
      console.error('Failed to save user preferences:', writeError.message);
      return fail(500, { error: 'Could not save preferences. Please try again.' });
    }

    return { success: true, message: "Preferences saved. Active for tomorrow's 06:00 UTC scan." };
  }
};
