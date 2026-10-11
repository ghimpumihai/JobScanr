"""Application submission, CV processing, and ATS integrations."""

from __future__ import annotations

import httpx

from jobs.apply.base import (
    BaseSubmitter,
    ManualApplySubmitter,
    QuestionOption,
    QuestionType,
    ScreeningQuestion,
    SubmissionResult,
    SubmitResponse,
    get_candidate_names,
    get_candidate_phone,
    map_screening_question,
)
from jobs.apply.greenhouse import GreenhouseSubmitter
from jobs.apply.lever import LeverSubmitter


def get_submitter(platform: str, client: httpx.AsyncClient | None = None) -> BaseSubmitter:
    """Resolve the appropriate submitter for a given ATS platform."""
    plat = (platform or "").lower().strip()
    if plat == "greenhouse":
        return GreenhouseSubmitter(client=client)
    if plat == "lever":
        return LeverSubmitter(client=client)
    return ManualApplySubmitter(client=client)


__all__ = [
    "BaseSubmitter",
    "GreenhouseSubmitter",
    "LeverSubmitter",
    "ManualApplySubmitter",
    "QuestionOption",
    "QuestionType",
    "ScreeningQuestion",
    "SubmissionResult",
    "SubmitResponse",
    "get_candidate_names",
    "get_candidate_phone",
    "get_submitter",
    "map_screening_question",
]
