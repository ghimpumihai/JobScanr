"""Typed data models for JobScanr."""

from typing import NotRequired, TypedDict


class Company(TypedDict):
    """Company record stored in the database or used by scrapers."""

    id: NotRequired[int]
    name: str
    ats_platform: str
    ats_identifier: str
    career_url: NotRequired[str | None]
    company_name: NotRequired[str]  # Alias in seed data


class JobPosting(TypedDict):
    """Core job posting produced by ATS scrapers and persisted to DB."""

    external_id: str
    title: str
    location: str | None
    department: str | None
    url: str | None
    description: str | None
    # Optional metadata set by scrapers or pipeline stages
    ats_identifier: NotRequired[str | None]
    company_id: NotRequired[int]
    company_name: NotRequired[str]
    ats_platform: NotRequired[str]
    google_level: NotRequired[str | None]
    external_path: NotRequired[str | None]
    compensation: NotRequired[str | None]
    application_deadline: NotRequired[str | None]
    id: NotRequired[int]
    first_seen_at: NotRequired[str | None]
    last_seen_at: NotRequired[str | None]
    notified_at: NotRequired[str | None]


class EnrichedJobPosting(JobPosting):
    """Job posting enriched with detailed description, deadline, or compensation."""

    description: str | None
    compensation: NotRequired[str | None]
    application_deadline: NotRequired[str | None]


class User(TypedDict):
    """User profile and configuration."""

    id: NotRequired[int]
    auth_user_id: str
    email: str
    resume_data: dict
    profile_filters: dict
    screening_defaults: dict
    auto_apply_mode: NotRequired[str]
    max_daily_applications: NotRequired[int]
    max_apps_per_company: NotRequired[int]
    gdpr_consent_at: NotRequired[str]
    created_at: NotRequired[str]


class UserJobMatch(TypedDict):
    """Match record between a user and a job posting."""

    id: NotRequired[int]
    user_id: int
    job_posting_id: int
    match_score: NotRequired[float | None]
    notified_at: NotRequired[str | None]
    created_at: NotRequired[str]


class Application(TypedDict):
    """Application record tracking submission pipeline status."""

    id: NotRequired[int]
    user_id: int
    job_posting_id: int
    status: NotRequired[str]
    attempt_token: NotRequired[str | None]
    attempts: NotRequired[int]
    locked_at: NotRequired[str | None]
    next_attempt_at: NotRequired[str | None]
    resume_snapshot: NotRequired[dict | None]
    submitted_payload: NotRequired[dict | None]
    created_at: NotRequired[str]


class ApplicationEvent(TypedDict):
    """Audit log event for application status transitions."""

    id: NotRequired[int]
    application_id: int
    from_status: str | None
    to_status: str
    reason: NotRequired[str | None]
    created_at: NotRequired[str]
