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
