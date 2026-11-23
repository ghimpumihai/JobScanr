import { fail, redirect } from '@sveltejs/kit';
import type { PageServerLoad, Actions } from './$types';
import type { UserProfile } from '$lib/types';
import { isSupabaseConfigured } from '$lib/supabase/server';
import { checkCvFile } from '$lib/cvFile';
import { safeHttpUrl } from '$lib/safeUrl';

const MOCK_PROFILE: UserProfile = {
  id: 1,
  email: 'stefan@example.com',
  full_name: 'Stefan Ghimpu',
  phone: '+40 700 000 000',
  location: 'Bucharest, Romania',
  linkedin: 'https://linkedin.com/in/example',
  github: 'https://github.com/example',
  resume_filename: 'stefan_ghimpu_cv_2026.pdf',
  resume_size_kb: 142,
  resume_uploaded_at: 'Oct 12, 2026',
  resume_uploaded_at_raw: '2026-10-12T09:00:00+00:00',
  seniority_levels: ['Graduate / New Grad', 'Entry Level (0-1 yrs)', 'Junior (1-2 yrs)'],
  preferred_locations: ['London', 'Berlin', 'Amsterdam', 'Dublin', 'Paris', 'Remote EU'],
  target_keywords: ['Backend', 'Python', 'Go', 'Distributed Systems', 'Platform'],
  excluded_keywords: ['Senior', 'Lead', 'Principal', 'Staff', 'Clearance', 'C++'],
  work_authorization: 'yes',
  requires_sponsorship: 'no',
  years_experience: 1,
  notice_period_days: 30,
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
const MAX_TEXT_LENGTH = 120;
const MAX_URL_LENGTH = 300;
const URL_FIELDS = ['linkedin', 'github', 'portfolio'] as const;
// Active and Paused. auto_submit is refused by the database: nothing can be sent without an employer key (#48).
const AUTO_APPLY_MODES = ['approval_required', 'disabled'];
const DEMO_RESULT = { success: true, message: 'Demo mode: nothing is stored.' };

function isLiveUser(locals: App.Locals): boolean {
  return Boolean(locals.user && locals.supabase && isSupabaseConfigured() && locals.user.id !== 'demo-user-id');
}

/** undefined = field absent (leave stored value alone), '' = clear it. */
function parseText(formData: FormData, name: string): string | undefined {
  return formData.get(name)?.toString().trim();
}

/** undefined = field absent, '' = clear it, null = invalid. Never coerces: the worker would submit a bad value as 0. */
function parseInteger(raw: string | undefined, min: number, max: number): number | '' | null | undefined {
  if (!raw) return raw as '' | undefined;
  const value = Number(raw);
  return /^\d{1,3}$/.test(raw) && value >= min && value <= max ? value : null;
}

/** Returns a copy of `stored` with defined values set and empty ones removed; other keys are untouched. */
function merge(stored: Record<string, unknown> | null | undefined, changes: Record<string, unknown>) {
  const result = { ...(stored ?? {}) };
  for (const [key, value] of Object.entries(changes)) {
    if (value === '') delete result[key];
    else if (value !== undefined) result[key] = value;
  }
  return result;
}

/** P0001 = RAISE EXCEPTION in protect_user_worker_fields (db/schema.sql), whose messages are written for users. */
function writeFailure(error: { code?: string; message: string }, fallback: string) {
  console.error('Settings write failed:', error.message);
  return error.code === 'P0001' ? fail(400, { error: error.message }) : fail(500, { error: fallback });
}

const boolLabel = (value: unknown) => (value === true ? 'yes' : value === false ? 'no' : '');

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
  if (isLiveUser(locals)) {
    const { data, error } = await locals.supabase
      .from('users')
      .select('*')
      .eq('auth_user_id', locals.user!.id)
      .single();

    if (error || !data) {
      console.error('Failed to load user profile:', error?.message);
      return { profile: null, loadError: true };
    }

    const urls = data.resume_data?.urls ?? {};
    const liveProfile: UserProfile = {
      id: data.id,
      email: data.email,
      full_name: data.screening_defaults?.full_name ?? '',
      phone: data.resume_data?.phone,
      location: data.resume_data?.location,
      linkedin: urls.linkedin,
      github: urls.github,
      portfolio: urls.portfolio,
      resume_filename: data.resume_filename ?? undefined,
      resume_storage_path: data.resume_storage_path,
      resume_content_type: data.resume_content_type,
      resume_uploaded_at: data.resume_uploaded_at ? new Date(data.resume_uploaded_at).toLocaleDateString() : undefined,
      resume_uploaded_at_raw: data.resume_uploaded_at ?? undefined,
      resume_confirmed_at: data.resume_confirmed_at ?? undefined,
      seniority_levels: Object.keys(LEVEL_TOKENS).filter((label) =>
        LEVEL_TOKENS[label].some((t) => (data.profile_filters?.levels ?? []).includes(t))
      ),
      preferred_locations: data.profile_filters?.locations ?? [],
      // The matcher reads `titles`; this is the same list.
      target_keywords: data.profile_filters?.titles ?? [],
      excluded_keywords: data.profile_filters?.excluded_title_keywords ?? [],
      work_authorization: boolLabel(data.screening_defaults?.work_authorization),
      requires_sponsorship: boolLabel(data.screening_defaults?.requires_sponsorship),
      years_experience: data.screening_defaults?.years_experience,
      notice_period_days: data.screening_defaults?.notice_period_days,
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
    const fullName = parseText(formData, 'fullName');
    const workAuth = parseText(formData, 'workAuth');
    const sponsorship = parseText(formData, 'requiresSponsorship');
    const contact = { phone: parseText(formData, 'phone'), location: parseText(formData, 'location') };
    const urls = Object.fromEntries(URL_FIELDS.map((name) => [name, parseText(formData, name)]));
    const years = parseInteger(parseText(formData, 'yearsExperience'), 0, 50);
    const noticeDays = parseInteger(parseText(formData, 'noticePeriodDays'), 0, 365);

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
    if (fullName && fullName.split(/\s+/).length < 2) {
      return fail(400, { error: 'Enter your first and last name. Applications need both.' });
    }
    if ([fullName, contact.phone, contact.location].some((v) => v && v.length > MAX_TEXT_LENGTH)) {
      return fail(400, { error: `Name, phone and location can have at most ${MAX_TEXT_LENGTH} characters each.` });
    }
    if (Object.values(urls).some((v) => v && (v.length > MAX_URL_LENGTH || safeHttpUrl(v) === '#'))) {
      return fail(400, { error: 'Profile links must be full http:// or https:// addresses.' });
    }
    if (workAuth && workAuth !== 'yes' && workAuth !== 'no') {
      return fail(400, { error: 'Work authorization must be Yes or No.' });
    }
    if (sponsorship && sponsorship !== 'yes' && sponsorship !== 'no') {
      return fail(400, { error: 'Visa sponsorship must be Yes or No.' });
    }
    if (years === null) return fail(400, { error: 'Years of experience must be a whole number from 0 to 50.' });
    if (noticeDays === null) return fail(400, { error: 'Notice period must be a whole number of days from 0 to 365.' });

    if (!isLiveUser(locals)) return DEMO_RESULT;

    const { data: existingUser, error: readError } = await locals.supabase
      .from('users')
      .select('screening_defaults, profile_filters, resume_data')
      .eq('auth_user_id', locals.user!.id)
      .single();
    if (readError || !existingUser) {
      console.error('Failed to read user preferences:', readError?.message);
      return fail(500, { error: 'Could not load your current preferences. Nothing was saved.' });
    }

    const screening_defaults = merge(existingUser.screening_defaults, {
      full_name: fullName || undefined,
      // The apply worker expects real booleans here, never free text.
      work_authorization: workAuth ? workAuth === 'yes' : undefined,
      requires_sponsorship: sponsorship ? sponsorship === 'yes' : undefined,
      years_experience: years,
      notice_period_days: noticeDays
    });
    // Not screening_defaults: the worker matches its keys inside question text, so "location" would answer
    // "Do you need relocation support?".
    const resume_data = merge(existingUser.resume_data, {
      ...contact,
      urls: merge(existingUser.resume_data?.urls, urls)
    });
    const profile_filters = {
      ...(existingUser.profile_filters ?? {}),
      ...Object.fromEntries(Object.entries(lists).filter(([, v]) => v !== undefined))
    };

    const { error: writeError } = await locals.supabase
      .from('users')
      .update({ screening_defaults, profile_filters, resume_data })
      .eq('auth_user_id', locals.user!.id);
    if (writeError) return writeFailure(writeError, 'Could not save preferences. Please try again.');

    return { success: true, message: 'Preferences saved.' };
  },

  uploadCv: async ({ request, locals }) => {
    const file = (await request.formData()).get('cv');
    if (!(file instanceof File)) return fail(400, { error: 'Choose a CV file to upload.' });
    const bytes = new Uint8Array(await file.arrayBuffer());
    const cv = checkCvFile(file.name, bytes);
    if (!cv.ok) return fail(400, { error: cv.error });
    if (!isLiveUser(locals)) return DEMO_RESULT;

    const { data: previous, error: readError } = await locals.supabase
      .from('users')
      .select('resume_storage_path')
      .eq('auth_user_id', locals.user!.id)
      .single();
    if (readError || !previous) {
      console.error('Failed to read current CV:', readError?.message);
      return fail(500, { error: 'Could not load your profile. Nothing was uploaded.' });
    }

    // A new object per upload, removed only after the row points at it, so the row never names a missing file.
    const bucket = locals.supabase.storage.from('resumes');
    const path = `${locals.user!.id}/${crypto.randomUUID()}${cv.extension}`;
    const { error: uploadError } = await bucket.upload(path, bytes, { contentType: cv.contentType });
    if (uploadError) {
      console.error('CV upload failed:', uploadError.message);
      return fail(500, { error: 'The upload failed. Your previous CV, if any, is unchanged.' });
    }

    const { error: writeError } = await locals.supabase
      .from('users')
      .update({
        resume_storage_path: path,
        resume_filename: cv.filename,
        resume_content_type: cv.contentType,
        resume_uploaded_at: new Date().toISOString()
      })
      .eq('auth_user_id', locals.user!.id)
      .select('id')
      .single();
    if (writeError) {
      // No code = the connection failed, so the row may already point at the new file: keep it.
      if (!writeError.code) {
        console.error('CV row update unconfirmed:', writeError.message);
        return fail(500, { error: 'The connection failed. Reload to see which CV is active.' });
      }
      const { error: cleanupError } = await bucket.remove([path]);
      if (cleanupError) console.error('Could not remove unused CV:', cleanupError.message);
      return writeFailure(writeError, 'Could not save the new CV. Your previous CV, if any, is unchanged.');
    }

    if (previous.resume_storage_path) {
      const { error: cleanupError } = await bucket.remove([previous.resume_storage_path]);
      if (cleanupError) console.error('Could not remove replaced CV:', cleanupError.message);
    }
    return { success: true, message: 'CV uploaded.' };
  },

  downloadCv: async ({ locals }) => {
    if (!isLiveUser(locals)) return DEMO_RESULT;
    const { data, error } = await locals.supabase
      .from('users')
      .select('resume_storage_path, resume_filename')
      .eq('auth_user_id', locals.user!.id)
      .single();
    if (error) {
      console.error('Failed to read CV path:', error.message);
      return fail(500, { error: 'Could not load your CV. Please try again.' });
    }
    if (!data.resume_storage_path) return fail(404, { error: 'You have not uploaded a CV yet.' });

    const { data: link, error: linkError } = await locals.supabase.storage
      .from('resumes')
      .createSignedUrl(data.resume_storage_path, 60);
    if (linkError) {
      console.error('Failed to sign CV link:', linkError.message);
      return fail(500, { error: 'Could not create a download link. Please try again.' });
    }
    // Not the client's `download` option: it encodes the filename twice ("ș.pdf" becomes "%C8%99.pdf").
    redirect(303, `${link.signedUrl}&download=${encodeURIComponent(data.resume_filename ?? '')}`);
  },

  saveAutoApply: async ({ request, locals }) => {
    const mode = parseText(await request.formData(), 'autoApplyMode');
    if (!mode || !AUTO_APPLY_MODES.includes(mode)) return fail(400, { error: 'Choose Active or Paused.' });
    if (!isLiveUser(locals)) return DEMO_RESULT;

    const { error: writeError } = await locals.supabase
      .from('users')
      .update({ auto_apply_mode: mode })
      .eq('auth_user_id', locals.user!.id)
      .select('id')
      .single();
    if (writeError) return writeFailure(writeError, 'Could not save. Please try again.');
    return { success: true, message: mode === 'disabled' ? 'Paused.' : 'Active.' };
  }
};
