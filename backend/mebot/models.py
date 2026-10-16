"""SQLAlchemy ORM models. No FKs: integrity is enforced in the repos.

Every tenant-owned table carries ``bot_id``; repos always filter on it.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    Text,
    TypeDecorator,
    false,
    true,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


class UTCDateTime(TypeDecorator):
    """Stores UTC; always returns timezone-aware UTC datetimes (SQLite drops tzinfo)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime; use timezone-aware UTC")
        value = value.astimezone(UTC)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Base(DeclarativeBase):
    pass


class Bot(Base):
    __tablename__ = "bots"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    registration_consent: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    setup_completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class ChatSession(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    bot_id: Mapped[str] = mapped_column(Text, nullable=False)
    recruiter_name: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    __table_args__ = (Index("ix_sessions_bot_id", "bot_id"),)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    bot_id: Mapped[str] = mapped_column(Text, nullable=False)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    # The model said it couldn't answer from the profile ([[UNANSWERED]] marker).
    unanswered: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    # Written by the owner (Telegram reply-back), not by the model.
    from_owner: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    __table_args__ = (
        Index("ix_messages_bot_id", "bot_id"),
        Index("ix_messages_session_id_created_at", "session_id", "created_at"),
    )


class AccessLog(Base):
    __tablename__ = "access_log"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    bot_id: Mapped[str] = mapped_column(Text, nullable=False)
    session_id: Mapped[str | None] = mapped_column(Text)
    event: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    __table_args__ = (Index("ix_access_log_bot_id", "bot_id"),)


class Admin(Base):
    __tablename__ = "admins"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(Text, nullable=False)  # stored lowercased
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    bot_id: Mapped[str | None] = mapped_column(Text, nullable=True)  # hosted mode, later
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    __table_args__ = (Index("ux_admins_email", "email", unique=True),)


class AdminSession(Base):
    __tablename__ = "admin_sessions"
    id: Mapped[str] = mapped_column(Text, primary_key=True)  # sha256(token) hex
    admin_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    ip: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        Index("ix_admin_sessions_admin_id", "admin_id"),
        Index("ix_admin_sessions_expires_at", "expires_at"),
    )


class LLMConfig(Base):
    __tablename__ = "llm_configs"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    bot_id: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    base_url: Mapped[str | None] = mapped_column(Text)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text)  # never the plaintext key
    api_key_last4: Mapped[str | None] = mapped_column(Text)
    temperature: Mapped[float] = mapped_column(Float, default=0.4, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, default=600, nullable=False)
    last_tested_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    __table_args__ = (Index("ux_llm_configs_bot_id", "bot_id", unique=True),)


# --- structured profile (migration 0005) ---------------------------------------------
# Every table: uuid id, bot_id, timestamps, soft delete; list tables add sort_order.
# JSON list columns (highlights, tech) are TEXT holding a JSON array of strings.


class _ProfileRow:
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    bot_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class _ListRow(_ProfileRow):
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


def _bot_ix(table: str, unique: bool = False) -> tuple:
    ix = (Index(f"ix_{table}_bot_id_deleted_at", "bot_id", "deleted_at"),)
    if unique:
        ix += (Index(f"ux_{table}_bot_id", "bot_id", unique=True),)
    return ix


class ProfileIdentity(_ProfileRow, Base):
    __tablename__ = "profile_identity"
    full_name: Mapped[str] = mapped_column(Text, default="", nullable=False)
    headline: Mapped[str] = mapped_column(Text, default="", nullable=False)
    location: Mapped[str] = mapped_column(Text, default="", nullable=False)
    open_to: Mapped[str] = mapped_column(Text, default="", nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    email_public: Mapped[str | None] = mapped_column(Text)
    phone_public: Mapped[str | None] = mapped_column(Text)
    notice_period: Mapped[str | None] = mapped_column(Text)
    salary_expectation: Mapped[str | None] = mapped_column(Text)
    work_authorization: Mapped[str | None] = mapped_column(Text)
    photo_url: Mapped[str | None] = mapped_column(Text)
    # Assistant persona (migration 0009): he/him | she/her | they/them, and the first bubble.
    pronouns: Mapped[str] = mapped_column(
        Text, default="they/them", server_default="they/them", nullable=False
    )
    assistant_greeting: Mapped[str | None] = mapped_column(Text)
    # Which experiences count toward total experience (see profile.facts).
    count_internships: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    count_freelance: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    __table_args__ = _bot_ix("profile_identity", unique=True)


class ProfileNotes(_ProfileRow, Base):
    __tablename__ = "profile_notes"
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    __table_args__ = _bot_ix("profile_notes", unique=True)


class ProfileLink(_ListRow, Base):
    __tablename__ = "profile_links"
    # A contact channel (migration 0010): value is canonical for its kind (mebot.channels).
    label: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(
        Text, default="website", server_default="website", nullable=False
    )
    share: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    __table_args__ = _bot_ix("profile_links")


class Experience(_ListRow, Base):
    __tablename__ = "experiences"
    company: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    employment_type: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    start_month: Mapped[str] = mapped_column(Text, nullable=False)
    end_month: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    highlights: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    tech: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    __table_args__ = _bot_ix("experiences")


class Education(_ListRow, Base):
    __tablename__ = "educations"
    institution: Mapped[str] = mapped_column(Text, nullable=False)
    degree: Mapped[str] = mapped_column(Text, nullable=False)
    field: Mapped[str | None] = mapped_column(Text)
    start_month: Mapped[str] = mapped_column(Text, nullable=False)
    end_month: Mapped[str | None] = mapped_column(Text)
    grade: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    __table_args__ = _bot_ix("educations")


class Skill(_ListRow, Base):
    __tablename__ = "skills"
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text)
    level: Mapped[str | None] = mapped_column(Text)
    years_override: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)
    __table_args__ = _bot_ix("skills")


class Project(_ListRow, Base):
    __tablename__ = "projects"
    name: Mapped[str] = mapped_column(Text, nullable=False)
    tagline: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    problem: Mapped[str | None] = mapped_column(Text)
    my_role: Mapped[str | None] = mapped_column(Text)
    frontend: Mapped[str | None] = mapped_column(Text)
    backend: Mapped[str | None] = mapped_column(Text)
    infra: Mapped[str | None] = mapped_column(Text)
    data_ai: Mapped[str | None] = mapped_column(Text)
    highlights: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    tech: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    repo_url: Mapped[str | None] = mapped_column(Text)
    live_url: Mapped[str | None] = mapped_column(Text)
    start_month: Mapped[str | None] = mapped_column(Text)
    end_month: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    __table_args__ = _bot_ix("projects")


class Interest(_ListRow, Base):
    __tablename__ = "interests"
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # hobby | interest
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    __table_args__ = _bot_ix("interests")


class Faq(_ListRow, Base):
    __tablename__ = "faqs"
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = _bot_ix("faqs")


class AvoidTopic(_ListRow, Base):
    __tablename__ = "avoid_topics"
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    reply: Mapped[str | None] = mapped_column(Text)
    __table_args__ = _bot_ix("avoid_topics")


# --- chat limits (migration 0007) ----------------------------------------------------


class BotLimits(Base):
    __tablename__ = "bot_limits"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    bot_id: Mapped[str] = mapped_column(Text, nullable=False)
    per_ip_per_minute: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    per_ip_per_day: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    per_session_messages: Mapped[int] = mapped_column(Integer, default=40, nullable=False)
    sessions_per_ip_per_hour: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    daily_message_cap: Mapped[int] = mapped_column(Integer, default=500, nullable=False)
    daily_token_cap: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_message_chars: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
    history_turns: Mapped[int] = mapped_column(Integer, default=12, nullable=False)
    paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    paused_message: Mapped[str | None] = mapped_column(Text)
    turnstile_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    __table_args__ = (Index("ux_bot_limits_bot_id", "bot_id", unique=True),)


class UsageCounter(Base):
    __tablename__ = "usage_counters"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    bot_id: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    window_start: Mapped[str] = mapped_column(Text, nullable=False)
    messages: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    __table_args__ = (
        Index("ux_usage_counters_window", "bot_id", "scope", "key", "window_start", unique=True),
        Index("ix_usage_counters_updated_at", "updated_at"),
    )


# --- telegram (migration 0008) -------------------------------------------------------


class TelegramConfig(Base):
    __tablename__ = "telegram_configs"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    bot_id: Mapped[str] = mapped_column(Text, nullable=False)
    bot_token_encrypted: Mapped[str | None] = mapped_column(Text)  # never the plaintext
    bot_token_last4: Mapped[str | None] = mapped_column(Text)
    bot_username: Mapped[str | None] = mapped_column(Text)
    chat_id: Mapped[str | None] = mapped_column(Text)
    link_code_hash: Mapped[str | None] = mapped_column(Text)
    link_code_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    mode: Mapped[str] = mapped_column(Text, default="polling", nullable=False)
    webhook_secret: Mapped[str | None] = mapped_column(Text)
    last_update_id: Mapped[int | None] = mapped_column(BigInteger)
    notify_new_session: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_every_question: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notify_unanswered: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_contact: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_limits: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    daily_digest: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    digest_hour: Mapped[int] = mapped_column(Integer, default=21, nullable=False)
    timezone: Mapped[str] = mapped_column(Text, default="UTC", nullable=False)
    last_digest_date: Mapped[str | None] = mapped_column(Text)
    last_cap_alert_date: Mapped[str | None] = mapped_column(Text)
    last_leak_alert_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    __table_args__ = (Index("ux_telegram_configs_bot_id", "bot_id", unique=True),)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    bot_id: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    session_id: Mapped[str | None] = mapped_column(Text)
    ref_message_id: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    __table_args__ = (
        Index("ix_notifications_status_next_attempt_at", "status", "next_attempt_at"),
        Index("ix_notifications_bot_id", "bot_id"),
        Index("ix_notifications_telegram_message_id", "telegram_message_id"),
    )


class Contact(Base):
    __tablename__ = "contacts"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    bot_id: Mapped[str] = mapped_column(Text, nullable=False)
    session_id: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    company: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    __table_args__ = (Index("ix_contacts_bot_id_deleted_at", "bot_id", "deleted_at"),)


# --- learning loop (migration 0009) --------------------------------------------------


class OpenQuestion(Base):
    """A professional question the bot couldn't answer, grouped with its rephrasings."""

    __tablename__ = "open_questions"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    bot_id: Mapped[str] = mapped_column(Text, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)  # first-seen wording
    normalized: Mapped[str] = mapped_column(Text, nullable=False)
    ask_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    first_asked_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    last_asked_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    last_session_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="open", nullable=False)
    answered_fact_id: Mapped[str | None] = mapped_column(Text)
    # Telegram ping throttle: first ask, then at most once per 24h.
    last_notified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    __table_args__ = (Index("ix_open_questions_bot_id_status", "bot_id", "status"),)


class LearnedFact(Base):
    """An owner-taught fact. Only ``approved`` and not soft-deleted facts reach the bot."""

    __tablename__ = "learned_facts"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    bot_id: Mapped[str] = mapped_column(Text, nullable=False)
    open_question_id: Mapped[str | None] = mapped_column(Text)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer_raw: Mapped[str] = mapped_column(Text, nullable=False)
    fact_text: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_section: Mapped[str] = mapped_column(Text, default="learned", nullable=False)
    suggested_field: Mapped[str | None] = mapped_column(Text)
    suggested_value: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="pending", nullable=False)
    source: Mapped[str] = mapped_column(Text, default="admin", nullable=False)
    needs_review: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    __table_args__ = (
        Index("ix_learned_facts_bot_id_status_deleted_at", "bot_id", "status", "deleted_at"),
    )


# --- widget (migration 0011) ---------------------------------------------------------


class WidgetSettings(Base):
    __tablename__ = "widget_settings"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    bot_id: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allowed_origins: Mapped[str] = mapped_column(Text, default="[]", nullable=False)  # JSON
    allow_any_origin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    primary_color: Mapped[str] = mapped_column(Text, default="#0f766e", nullable=False)
    theme: Mapped[str] = mapped_column(Text, default="auto", nullable=False)
    position: Mapped[str] = mapped_column(Text, default="right", nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    launcher_label: Mapped[str | None] = mapped_column(Text)
    suggested_questions: Mapped[str] = mapped_column(Text, default="[]", nullable=False)  # JSON
    show_orb: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auto_open_seconds: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    __table_args__ = (Index("ux_widget_settings_bot_id", "bot_id", unique=True),)
