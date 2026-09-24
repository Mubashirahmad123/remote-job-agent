"""Pydantic schemas for Phase 1 read API.

Tracker header choice (documented):
  Canonical tracker header is tools/application_tracker.py:12-16
  (job_title, company, apply_url, match_score, applied_date, status,
  follow_up_date, notes, source, salary, contact, last_updated) — NOT the
  tools/sheet_writer.py APPLIED_COLUMNS fork (COLUMNS + applied_at/notes),
  because the tracker module owns APPLIED-tab reads/writes (mark_applied,
  update_status, list_applications, get_stats) and its header is what
  get_applied_sheet() creates on a fresh tab.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _empty_to_none(value: Any) -> Any:
    """Normalize empty/whitespace-only strings to None ("" -> null)."""
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def _parse_optional_bool(value: Any) -> Any:
    """Coerce bool-ish strings (\"false\"/\"0\"/\"no\"/\"off\") -> bool; \"\" -> None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s == "":
            return None
        if s in ("true", "1", "yes", "y", "on", "computed", "done"):
            return True
        if s in ("false", "0", "no", "n", "off", "none", "null"):
            return False
        return None
    return None


def _parse_optional_float(value: Any) -> Any:
    """Coerce "" -> None and numeric strings -> float; invalid -> None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        if s == "":
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


_TEXT_FIELDS = (
    "job_title", "company", "salary", "tech_stack", "timezone",
    "apply_url", "summary", "posted_date_iso", "source",
    "match_reason", "scraped_at", "status", "job_fingerprint",
    "selected_cv_path", "selected_cv", "location", "job_type",
)

_SCORE_FIELDS = (
    "match_score", "ranking_score", "keyword_score",
    "semantic_score", "freshness_boost",
)


class JobOut(BaseModel):
    """One job row: base sheet columns + curator enrichment (all nullable)."""

    # Base columns (tools/sheet_writer.py COLUMNS)
    job_title: Optional[str] = None
    company: Optional[str] = None
    salary: Optional[str] = None
    tech_stack: Optional[str] = None
    timezone: Optional[str] = None
    apply_url: Optional[str] = None
    summary: Optional[str] = None
    posted_date_iso: Optional[str] = None
    source: Optional[str] = None
    match_score: Optional[float] = None
    match_reason: Optional[str] = None
    scraped_at: Optional[str] = None
    status: Optional[str] = None
    job_fingerprint: Optional[str] = None

    # Curator enrichment (agents/curator.py curate(); curated_jobs.json).
    # Absent enrichment -> null, never crash.
    ranking_score: Optional[float] = None
    keyword_score: Optional[float] = None
    semantic_score: Optional[float] = None
    freshness_boost: Optional[float] = None
    semantic_computed: Optional[bool] = None
    selected_cv_path: Optional[str] = None
    selected_cv: Optional[str] = None
    location_tags: Optional[List[str]] = None
    location: Optional[str] = None
    job_type: Optional[str] = None

    # Which sheet tab this row came from.
    tab: Optional[str] = None

    @field_validator(*_TEXT_FIELDS, mode="before", check_fields=False)
    @classmethod
    def _normalize_empty(cls, v: Any) -> Any:
        return _empty_to_none(v)

    @field_validator(*_SCORE_FIELDS, mode="before", check_fields=False)
    @classmethod
    def _normalize_score(cls, v: Any) -> Any:
        return _parse_optional_float(v)

    @field_validator("semantic_computed", mode="before", check_fields=False)
    @classmethod
    def _normalize_bool(cls, v: Any) -> Any:
        return _parse_optional_bool(v)


_TRACKER_TEXT_FIELDS = (
    "job_title", "company", "apply_url", "applied_date", "status",
    "follow_up_date", "notes", "source", "salary", "contact",
    "last_updated",
)


class TrackerEntry(BaseModel):
    """One APPLIED-tab row per tools/application_tracker.py:12-16 header."""

    job_title: Optional[str] = None
    company: Optional[str] = None
    apply_url: Optional[str] = None
    match_score: Optional[float] = None
    applied_date: Optional[str] = None
    status: Optional[str] = None
    follow_up_date: Optional[str] = None
    notes: Optional[str] = None
    source: Optional[str] = None
    salary: Optional[str] = None
    contact: Optional[str] = None
    last_updated: Optional[str] = None

    @field_validator(*_TRACKER_TEXT_FIELDS, mode="before", check_fields=False)
    @classmethod
    def _normalize_empty(cls, v: Any) -> Any:
        return _empty_to_none(v)

    @field_validator("match_score", mode="before", check_fields=False)
    @classmethod
    def _normalize_score(cls, v: Any) -> Any:
        return _parse_optional_float(v)


class TrackerUpdate(BaseModel):
    """PATCH /api/tracker/{fp} body. Status whitelist mirrors update_status()."""

    status: str = Field(description="applied|interviewing|offer|rejected|withdrawn|ghosted")
    notes: Optional[str] = None

    @field_validator("notes", mode="before", check_fields=False)
    @classmethod
    def _normalize_notes(cls, v: Any) -> Any:
        return _empty_to_none(v)


VALID_TRACKER_STATUSES = frozenset(
    {"applied", "interviewing", "offer", "rejected", "withdrawn", "ghosted"}
)


class HealthOut(BaseModel):
    status: str = "ok"
    sheets_configured: bool = False
    curated_jobs_loaded: int = 0
    data_source: str = "empty"  # sheets|snapshot|empty (see api.cache.data_source)


_CV_TEXT_FIELDS = (
    "name", "email", "phone", "location", "seniority",
    "_source_file", "_parsed_at",
)

_CV_LIST_FIELDS = (
    "skills", "frameworks", "databases", "languages", "preferred_titles",
)


class CvVariant(BaseModel):
    """One CV file discovered by tools/cv_library.py (name + domain tags)."""

    name: Optional[str] = None
    tags: List[str] = Field(default_factory=list)

    @field_validator("name", mode="before", check_fields=False)
    @classmethod
    def _normalize_name(cls, v: Any) -> Any:
        return _empty_to_none(v)


class CvProfileOut(BaseModel):
    """Cached CV profile from tools/cv_parser.py (cheap cache read only).

    Extra keys pass through (model_config extra="allow") so future parser
    fields don't break the API. Empty strings -> null, like JobOut.
    """

    model_config = ConfigDict(extra="allow")

    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    seniority: Optional[str] = None
    years_experience: Optional[float] = None
    skills: Optional[List[str]] = None
    frameworks: Optional[List[str]] = None
    databases: Optional[List[str]] = None
    languages: Optional[List[str]] = None
    preferred_titles: Optional[List[Any]] = None
    experience: Optional[List[Any]] = None
    education: Optional[List[Any]] = None

    @field_validator(*_CV_TEXT_FIELDS, mode="before", check_fields=False)
    @classmethod
    def _normalize_empty(cls, v: Any) -> Any:
        return _empty_to_none(v)

    @field_validator("years_experience", mode="before", check_fields=False)
    @classmethod
    def _normalize_years(cls, v: Any) -> Any:
        return _parse_optional_float(v)


class CvProfileUpdate(BaseModel):
    """PUT /api/cv/profile body — user edits from Resume Studio.

    All fields optional; only whitelisted contact + skill fields are merged
    into the on-disk cv_parser cache. Extra keys allowed but ignored on save
    (never crash on future frontend fields).
    """

    model_config = ConfigDict(extra="allow")

    name: Optional[str] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    linkedin: Optional[str] = None
    linkedin_url: Optional[str] = None
    location: Optional[str] = None
    skills: Optional[List[str]] = None
    core_skills: Optional[List[str]] = None

    @field_validator("skills", "core_skills", mode="before", check_fields=False)
    @classmethod
    def _coerce_skill_list(cls, v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, str):
            return [s.strip() for s in v.replace("\n", ",").split(",") if s.strip()]
        return v
