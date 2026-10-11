"""Base ATS submitter interface, domain models, and question mapping engine.

Implements stateless question schema extraction, mapping against candidate profiles,
and unauthenticated submission lifecycle.
"""

from __future__ import annotations

import io
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

import httpx

from models import JobPosting, User

logger = logging.getLogger(__name__)


class QuestionType(str, Enum):
    SHORT_TEXT = "short_text"  # Single-line string input
    LONG_TEXT = "long_text"  # Multiline / essay textarea
    SINGLE_SELECT = "single_select"  # Dropdown / radio options
    MULTI_SELECT = "multi_select"  # Multiple choice checkboxes
    FILE = "file"  # Additional file attachment
    BOOLEAN = "boolean"  # Single checkbox / Yes-No toggle


@dataclass
class QuestionOption:
    id: str | int
    label: str


@dataclass
class ScreeningQuestion:
    id: str | int
    label: str
    question_type: QuestionType
    required: bool
    options: list[QuestionOption] = field(default_factory=list)
    raw_field_name: str | None = None
    description: str | None = None


@dataclass
class SubmissionResult:
    status: Literal["ready", "needs_review", "manual_apply"]
    payload: dict[str, Any] = field(default_factory=dict)
    unmapped_questions: list[ScreeningQuestion] = field(default_factory=list)
    reason: str | None = None


@dataclass
class SubmitResponse:
    status: Literal["submitted", "needs_review", "manual_apply", "stale_closed", "failed"]
    external_application_id: str | None = None
    redirect_url: str | None = None
    reason: str | None = None
    http_status: int | None = None
    error_message: str | None = None


def get_candidate_names(user: User) -> tuple[str, str, str]:
    """Extract (full_name, first_name, last_name) from user profile."""
    resume_data = user.get("resume_data") or {}
    first_name = (resume_data.get("first_name") or "").strip()
    last_name = (resume_data.get("last_name") or "").strip()
    full_name = (resume_data.get("full_name") or resume_data.get("name") or "").strip()

    if first_name and last_name:
        if not full_name:
            full_name = f"{first_name} {last_name}"
        return full_name, first_name, last_name

    if full_name:
        parts = full_name.split(None, 1)
        first_name = parts[0]
        last_name = parts[1] if len(parts) > 1 else ""
        return full_name, first_name, last_name

    email_local = user.get("email", "").split("@")[0].replace(".", " ").title()
    parts = email_local.split(None, 1)
    first_name = parts[0] if parts else "Candidate"
    last_name = parts[1] if len(parts) > 1 else ""
    full_name = f"{first_name} {last_name}".strip()
    return full_name, first_name, last_name


def get_candidate_phone(user: User) -> str:
    resume_data = user.get("resume_data") or {}
    return str(resume_data.get("phone") or user.get("screening_defaults", {}).get("phone") or "").strip()


def get_candidate_location(user: User) -> str:
    resume_data = user.get("resume_data") or {}
    defaults = user.get("screening_defaults") or {}
    return str(
        defaults.get("location") or defaults.get("current_location") or resume_data.get("location") or ""
    ).strip()


def get_candidate_url(user: User, platform: str) -> str:
    """Retrieve profile URL for a given platform (linkedin, github, portfolio, website, twitter)."""
    resume_data = user.get("resume_data") or {}
    defaults = user.get("screening_defaults") or {}
    urls = resume_data.get("urls") or defaults.get("urls") or {}

    plat = platform.lower()
    if plat in urls:
        return str(urls[plat]).strip()
    if plat in resume_data:
        return str(resume_data[plat]).strip()
    if plat in defaults:
        return str(defaults[plat]).strip()

    # Common aliases
    if plat in ("portfolio", "website"):
        return str(urls.get("portfolio") or urls.get("website") or resume_data.get("website") or "").strip()
    return ""


def _match_select_option(options: list[QuestionOption], desired_text: str | bool) -> QuestionOption | None:
    """Find the best matching option for a given boolean or string target."""
    if isinstance(desired_text, bool):
        target_labels = ("yes", "true") if desired_text else ("no", "false")
        for opt in options:
            clean = opt.label.strip().lower()
            if any(tl in clean for tl in target_labels):
                return opt
        return None

    target = str(desired_text).strip().lower()
    for opt in options:
        if opt.label.strip().lower() == target:
            return opt

    for opt in options:
        if target in opt.label.strip().lower():
            return opt
    return None


def map_screening_question(question: ScreeningQuestion, user: User) -> tuple[Any | None, bool]:
    """Map a single screening question against candidate profile and screening defaults.

    Returns:
        tuple[Any | None, bool]: (mapped_value, is_confident)
        is_confident is True if the question was unambiguously resolved, False otherwise.
    """
    defaults = user.get("screening_defaults") or {}
    raw_label = question.label or ""
    clean_label = re.sub(r"[^\w\s]", "", raw_label).lower().strip()

    # 1. Work Authorization
    if any(
        kw in clean_label
        for kw in (
            "legally authorized",
            "authorized to work",
            "legal right to work",
            "work authorization",
            "eligible to work",
            "right to work",
        )
    ):
        work_auth = defaults.get("work_authorization")
        if work_auth is not None:
            is_auth = bool(work_auth)
            if question.question_type in (QuestionType.SINGLE_SELECT, QuestionType.MULTI_SELECT):
                matched = _match_select_option(question.options, is_auth)
                if matched:
                    return matched.id, True
                return None, False
            if question.question_type == QuestionType.BOOLEAN:
                return is_auth, True
            return ("Yes" if is_auth else "No"), True

    # 2. Visa Sponsorship
    if any(
        kw in clean_label
        for kw in (
            "require sponsorship",
            "visa sponsorship",
            "require visa",
            "sponsorship for employment",
            "h1b",
            "require now or in the future",
        )
    ):
        sponsorship = defaults.get("requires_sponsorship")
        if sponsorship is not None:
            req_spon = bool(sponsorship)
            if question.question_type in (QuestionType.SINGLE_SELECT, QuestionType.MULTI_SELECT):
                matched = _match_select_option(question.options, req_spon)
                if matched:
                    return matched.id, True
                return None, False
            if question.question_type == QuestionType.BOOLEAN:
                return req_spon, True
            return ("Yes" if req_spon else "No"), True

    # 3. Years of Experience
    if any(kw in clean_label for kw in ("years of experience", "how many years", "experience in years")):
        years = defaults.get("years_experience")
        if years is not None:
            try:
                years_num = int(years)
            except (ValueError, TypeError):
                years_num = 0

            if question.question_type in (QuestionType.SINGLE_SELECT, QuestionType.MULTI_SELECT):
                # Try finding range containing years_num
                for opt in question.options:
                    nums = [int(n) for n in re.findall(r"\d+", opt.label)]
                    if len(nums) == 2 and nums[0] <= years_num <= nums[1]:
                        return opt.id, True
                    if len(nums) == 1 and ("+" in opt.label or "more" in opt.label.lower()) and years_num >= nums[0]:
                        return opt.id, True
                    if len(nums) == 1 and nums[0] == years_num:
                        return opt.id, True
                return None, False
            return str(years_num), True

    # 4. Notice Period
    if any(kw in clean_label for kw in ("notice period", "how soon can you start", "availability to start")):
        notice_days = defaults.get("notice_period_days")
        if notice_days is not None:
            try:
                days = int(notice_days)
            except (ValueError, TypeError):
                days = 0

            if question.question_type in (QuestionType.SINGLE_SELECT, QuestionType.MULTI_SELECT):
                if days <= 7:
                    matched = _match_select_option(question.options, "immediately")
                    if matched:
                        return matched.id, True
                matched = _match_select_option(question.options, f"{days}")
                if matched:
                    return matched.id, True
                return None, False
            return (f"{days} days" if days > 0 else "Immediately"), True

    # 5. Location / Current City
    if any(kw in clean_label for kw in ("current location", "where are you located", "city and country", "based in")):
        loc = get_candidate_location(user)
        if loc:
            if question.question_type in (QuestionType.SINGLE_SELECT, QuestionType.MULTI_SELECT):
                matched = _match_select_option(question.options, loc)
                if matched:
                    return matched.id, True
                return None, False
            return loc, True

    # 6. Candidate Profile URLs
    for plat in ("linkedin", "github", "portfolio", "website", "twitter"):
        if plat in clean_label:
            url = get_candidate_url(user, plat)
            if url:
                return url, True

    # 7. Exact key match in screening_defaults
    for key, val in defaults.items():
        clean_key = re.sub(r"[^\w\s]", "", key).lower().strip()
        if clean_key and clean_key in clean_label:
            if question.question_type in (QuestionType.SINGLE_SELECT, QuestionType.MULTI_SELECT):
                matched = _match_select_option(question.options, str(val))
                if matched:
                    return matched.id, True
                return None, False
            if question.question_type == QuestionType.BOOLEAN:
                return bool(val), True
            return str(val), True

    # 8. Open-ended / Essay Detection
    if question.question_type == QuestionType.LONG_TEXT or len(raw_label) > 100:
        # Complex essay question: cannot be answered automatically
        return None, False

    # Not confident
    return None, False


class BaseSubmitter(ABC):
    """Abstract submitter for public ATS job applications."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.client = client

    @abstractmethod
    async def fetch_questions(self, posting: JobPosting) -> list[ScreeningQuestion]:
        """Fetch and parse live screening questions for a job posting."""
        raise NotImplementedError

    @abstractmethod
    def map_and_validate_payload(
        self,
        user: User,
        posting: JobPosting,
        questions: list[ScreeningQuestion],
    ) -> SubmissionResult:
        """Map candidate profile to ATS fields and validate required questions."""
        raise NotImplementedError

    @abstractmethod
    async def submit(
        self,
        user: User,
        posting: JobPosting,
        payload: dict[str, Any],
        resume_stream: io.BytesIO,
        filename: str,
        content_type: str = "application/pdf",
    ) -> SubmitResponse:
        """Submit application payload and in-memory resume stream to ATS endpoint."""
        raise NotImplementedError

    async def preview_submission(self, user: User, posting: JobPosting) -> SubmissionResult:
        """Inspect question schema and preview mapping decision without dispatching HTTP POST."""
        questions = await self.fetch_questions(posting)
        return self.map_and_validate_payload(user, posting, questions)


class ManualApplySubmitter(BaseSubmitter):
    """Fallback submitter for ATS platforms requiring manual application (Ashby, SmartRecruiters, Teamtailor, Workday, Google)."""

    async def fetch_questions(self, posting: JobPosting) -> list[ScreeningQuestion]:
        return []

    def map_and_validate_payload(
        self,
        user: User,
        posting: JobPosting,
        questions: list[ScreeningQuestion],
    ) -> SubmissionResult:
        plat = posting.get("ats_platform") or "unknown"
        return SubmissionResult(
            status="manual_apply",
            payload={},
            unmapped_questions=[],
            reason=f"Platform '{plat}' requires manual application",
        )

    async def submit(
        self,
        user: User,
        posting: JobPosting,
        payload: dict[str, Any],
        resume_stream: io.BytesIO,
        filename: str,
        content_type: str = "application/pdf",
    ) -> SubmitResponse:
        plat = posting.get("ats_platform") or "unknown"
        return SubmitResponse(
            status="manual_apply",
            reason=f"Platform '{plat}' requires manual application",
            redirect_url=posting.get("url"),
        )
