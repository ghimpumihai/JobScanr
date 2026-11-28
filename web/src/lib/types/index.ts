export type ATSPlatform =
  | 'greenhouse'
  | 'lever'
  | 'workday'
  | 'ashby'
  | 'smartrecruiters'
  | 'teamtailor'
  | 'google';

export type ApplicationStatus =
  | 'queued'
  | 'pending_approval'
  | 'submitting'
  | 'submitted'
  | 'needs_review'
  | 'failed'
  | 'manual_apply'
  | 'stale_closed'
  | 'dismissed';

export type AutoApplyMode = 'approval_required' | 'auto_submit' | 'disabled';

export interface JobMatch {
  id: number;
  external_id: string;
  title: string;
  company_name: string;
  location: string;
  compensation?: string;
  ats_platform: ATSPlatform;
  url: string;
  match_score: number;
  department?: string;
  first_seen_at?: string;
}

export interface ApplicationRecord {
  id: number;
  title: string;
  company_name: string;
  location: string;
  ats_platform: ATSPlatform;
  status: ApplicationStatus;
  /** Posting link, already passed through safeHttpUrl ('#' when unsafe). */
  url: string;
  /** Pay as the posting states it, or null ("Salary not listed"). */
  compensation: string | null;
  added_at: string;
  /** When the user first opened the role; null shows the unread dot. */
  opened_at: string | null;
  /** The user's filter words found in the title or location. */
  matched: string[];
  /** Set by the database when the user marks it applied. */
  applied_at: string | null;
  last_seen_at: string | null;
}

/** A personal-fact question the user answers once and remote fill reuses (answer memory). Pending while answer is null. */
export interface SavedAnswer {
  id: number;
  question: string;
  answer: string | null;
  first_seen_at: string;
}

export interface UserProfile {
  id: number;
  email: string;
  full_name?: string;
  phone?: string;
  location?: string;
  linkedin?: string;
  github?: string;
  portfolio?: string;
  requires_sponsorship?: string;
  years_experience?: number;
  notice_period_days?: number;
  resume_filename?: string;
  resume_storage_path?: string;
  resume_content_type?: string;
  resume_uploaded_at?: string;
  /** Exact stored timestamp; resume_uploaded_at is formatted for display. */
  resume_uploaded_at_raw?: string;
  resume_confirmed_at?: string;
  resume_size_kb?: number;
  seniority_levels: string[];
  preferred_locations: string[];
  target_keywords?: string[];
  excluded_keywords: string[];
  work_authorization: string;
  auto_apply_mode: AutoApplyMode;
  max_daily_applications: number;
  max_apps_per_company: number;
  /** Opt-in to Groq drafts of open-ended answers in remote fill (#59). */
  llm_drafts_enabled: boolean;
  /** degree is a value from DEGREES in $lib/eeo. */
  education?: { school?: string; degree?: string; field_of_study?: string; graduation_year?: number };
  /** Values from EEO_FIELDS in $lib/eeo; missing = prefer_not (remote fill picks the form's decline option). */
  eeo?: { gender?: string; race?: string; veteran?: string; disability?: string };
}

export interface TelemetrySummary {
  feeds_online: number;
  total_feeds: number;
  scan_time: string;
  matches_today: number;
}
