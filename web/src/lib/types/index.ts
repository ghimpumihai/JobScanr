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
  | 'stale_closed';

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
  job_posting_id: number;
  title: string;
  company_name: string;
  location: string;
  ats_platform: ATSPlatform;
  status: ApplicationStatus;
  submitted_at?: string;
  scheduled_at?: string;
  attempt_token?: string;
  attempts?: number;
  screening_question?: string;
  drafted_answer?: string;
  work_authorization?: string;
  resume_snapshot?: Record<string, unknown>;
  submitted_payload?: Record<string, unknown>;
}

export interface UserProfile {
  id: number;
  email: string;
  full_name?: string;
  resume_filename?: string;
  resume_storage_path?: string;
  resume_content_type?: string;
  resume_uploaded_at?: string;
  resume_size_kb?: number;
  seniority_levels: string[];
  preferred_locations: string[];
  excluded_keywords: string[];
  work_authorization: string;
  auto_apply_mode: AutoApplyMode;
  max_daily_applications: number;
  max_apps_per_company: number;
}

export interface TelemetrySummary {
  feeds_online: number;
  total_feeds: number;
  scan_time: string;
  matches_today: number;
}
