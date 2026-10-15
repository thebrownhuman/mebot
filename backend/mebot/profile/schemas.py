"""Input schemas for the structured profile. Strings are stripped; blank optional
fields become None. Limits: short 200, long 5000, notes 20000, tag lists 30 x 200."""

import re
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    ValidationInfo,
    field_validator,
)

SHORT = 200
LONG = 5000
NOTES = 20000
MAX_TAGS = 30
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _blank_to_none(v):
    if isinstance(v, str) and not v.strip():
        return None
    return v


def _check_month(v: str | None) -> str | None:
    if v is not None and not MONTH_RE.match(v):
        raise ValueError("use YYYY-MM")
    return v


def _check_url(v: str | None) -> str | None:
    if v is None:
        return v
    m = re.match(r"^(https?)://([^/\s?#]+)", v, re.IGNORECASE)
    if not m:
        raise ValueError("must be an http(s) URL")
    return v


def _str(max_len: int, min_len: int = 0):
    return Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=max_len, min_length=min_len)
    ]


Required = _str(SHORT, 1)
Short = _str(SHORT)
Long = _str(LONG)
RequiredLong = _str(LONG, 1)
OptShort = Annotated[_str(SHORT) | None, BeforeValidator(_blank_to_none)]
OptLong = Annotated[_str(LONG) | None, BeforeValidator(_blank_to_none)]
Month = Annotated[str, StringConstraints(strip_whitespace=True), BeforeValidator(str)]
OptMonth = Annotated[str | None, BeforeValidator(_blank_to_none)]
Url = Annotated[_str(500, 1), BeforeValidator(str)]
OptUrl = Annotated[_str(500) | None, BeforeValidator(_blank_to_none)]
Tags = Annotated[list[_str(SHORT, 1)], Field(max_length=MAX_TAGS)]


class _In(BaseModel):
    # Clients may echo id/sort_order/timestamps back when editing: ignore them.
    model_config = ConfigDict(extra="ignore")


class _Dated(_In):
    """start_month / end_month: YYYY-MM, end >= start (end None = ongoing)."""

    @field_validator("start_month", "end_month", check_fields=False)
    @classmethod
    def _month(cls, v):
        return _check_month(v)

    @field_validator("end_month", check_fields=False)
    @classmethod
    def _end_after_start(cls, v, info: ValidationInfo):
        start = info.data.get("start_month")
        if v and start and v < start:
            raise ValueError("end month is before start month")
        return v


class IdentityIn(_In):
    full_name: Short = ""
    headline: Short = ""
    location: Short = ""
    open_to: Short = ""
    summary: Long = ""
    email_public: Annotated[EmailStr | None, BeforeValidator(_blank_to_none)] = None
    phone_public: OptShort = None
    notice_period: OptShort = None
    salary_expectation: OptShort = None
    work_authorization: OptShort = None
    photo_url: OptUrl = None
    count_internships: bool = False
    count_freelance: bool = True

    @field_validator("photo_url")
    @classmethod
    def _url(cls, v):
        return _check_url(v)


class NotesIn(_In):
    content: _str(NOTES) = ""


class LinkIn(_In):
    label: Required
    url: Url

    @field_validator("url")
    @classmethod
    def _url(cls, v):
        return _check_url(v)


class ExperienceIn(_Dated):
    company: Required
    title: Required
    employment_type: Annotated[
        Literal["full-time", "part-time", "contract", "internship", "freelance"] | None,
        BeforeValidator(_blank_to_none),
    ] = None
    location: OptShort = None
    start_month: Month
    end_month: OptMonth = None
    description: Long = ""
    highlights: Tags = []
    tech: Tags = []


class EducationIn(_Dated):
    institution: Required
    degree: Required
    field: OptShort = None
    start_month: Month
    end_month: OptMonth = None
    grade: OptShort = None
    description: OptLong = None


class SkillIn(_In):
    name: Required
    category: Annotated[
        Literal["language", "framework", "tool", "cloud", "soft", "other"] | None,
        BeforeValidator(_blank_to_none),
    ] = None
    level: Annotated[
        Literal["beginner", "intermediate", "advanced", "expert"] | None,
        BeforeValidator(_blank_to_none),
    ] = None
    years_override: float | None = Field(default=None, ge=0, le=80)
    notes: OptLong = None


class ProjectIn(_Dated):
    name: Required
    tagline: OptShort = None
    summary: RequiredLong
    problem: OptLong = None
    my_role: OptLong = None
    frontend: OptLong = None
    backend: OptLong = None
    infra: OptLong = None
    data_ai: OptLong = None
    highlights: Tags = []
    tech: Tags = []
    repo_url: OptUrl = None
    live_url: OptUrl = None
    start_month: OptMonth = None
    end_month: OptMonth = None
    status: Annotated[
        Literal["active", "completed", "archived"] | None, BeforeValidator(_blank_to_none)
    ] = None

    @field_validator("repo_url", "live_url")
    @classmethod
    def _urls(cls, v):
        return _check_url(v)


class InterestIn(_In):
    kind: Literal["hobby", "interest"]
    name: Required
    description: OptLong = None


class FaqIn(_In):
    question: _str(SHORT * 2, 1)
    answer: RequiredLong


class AvoidTopicIn(_In):
    topic: Required
    reply: OptLong = None


class OrderIn(_In):
    ids: list[str] = Field(max_length=1000)
