"""Runtime configuration. Everything comes from env vars (or a .env file)."""

import logging
import secrets
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent


class ConfigError(RuntimeError):
    """Raised for misconfiguration that should stop startup with a clear message."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # single = one bot, no tenancy. hosted = many owners, each with their own bot.
    mode: Literal["single", "hosted"] = "single"
    # Encrypts stored API keys and keys the IP hashes. Required when MODE=hosted; in single
    # mode one is generated once into <DATA_DIR>/secret.key. Changing it means re-entering
    # API keys.
    secret_key: str | None = None
    # Directory for the SQLite db and the generated secret key.
    data_dir: Path = BACKEND_DIR / "data"
    # Defaults to sqlite:///<data_dir>/mebot.db when unset.
    database_url: str = ""
    # "off" = no heartbeat, registration or update check: zero network calls to the registry.
    telemetry: Literal["on", "off"] = "on"
    # Where heartbeats / registrations go. Read once at startup.
    registry_url: str = "https://registry.shivanshmishra.in"
    # Background telemetry jobs (heartbeat, registration, update check). Tests turn them off.
    telemetry_workers: bool = True
    # Only the suggested base URL for the "ollama" provider; the model and provider
    # are chosen in setup / Admin -> AI Provider.
    ollama_host: str = "http://127.0.0.1:11434"
    # Comma-separated allowed browser origins (also used by the admin CSRF origin check).
    cors_origins: str = "http://localhost:5173"
    # If set, POST /api/setup must include a matching setup_token. Recommended when the
    # first boot is reachable from the internet.
    setup_token: str | None = None
    # Force the Secure flag on auth cookies (set when TLS terminates at a reverse proxy).
    cookie_secure: bool = False
    # Trust X-Forwarded-Proto / X-Forwarded-For from a reverse proxy.
    trust_proxy: bool = False
    # Optional Cloudflare Turnstile on new chats (also needs the toggle in Admin -> Limits).
    turnstile_site_key: str | None = None
    # Server-side Turnstile secret, paired with TURNSTILE_SITE_KEY.
    turnstile_secret_key: str | None = None
    # Public base URL (https://bot.example.com). Enables the Telegram webhook option and
    # "Open chat" links in notifications.
    public_url: str | None = None
    # Background Telegram tasks (poller, outbox, digest). Tests turn them off.
    telegram_workers: bool = True
    # Built frontend (npm run build). When it holds an index.html the backend serves the
    # whole UI (app, embed bundle, widget loader) with per-path cache headers.
    frontend_dist: Path = REPO_ROOT / "frontend" / "dist"
    # Optional token for GitHub imports (public data only; raises the 60/hour limit).
    # A token saved in Admin -> Import takes precedence.
    github_token: str | None = None
    # Profiles above this many (estimated) tokens are not sent whole: only the parts relevant
    # to each question are. Per-bot override in Admin -> Knowledge (auto / always / off).
    retrieval_threshold_tokens: int = 6000
    # Token budget for the retrieved profile excerpts in one prompt.
    retrieval_budget_tokens: int = 2500

    # --- Hosted mode (MODE=hosted) only; ignored in single mode. ---

    # Hosted mode needs Postgres (DATABASE_URL=postgresql+psycopg://...). Set to 1 to run
    # hosted on SQLite anyway: development only, one process, a warning on every start.
    allow_sqlite_hosted: bool = False
    # Optional wildcard domain: {slug}.HOSTED_DOMAIN serves that bot's recruiter page.
    # Without it, bots live at /b/{slug}.
    hosted_domain: str | None = None
    # Who may sign up: open (anyone), invite (needs an invite code), closed (nobody).
    signup_mode: Literal["open", "invite", "closed"] = "invite"
    # Outgoing mail (verification, password reset). Without SMTP_HOST mails are printed
    # to the log instead (development only).
    smtp_host: str | None = None
    # SMTP port; 587 uses STARTTLS, 465 implicit TLS.
    smtp_port: int = 587
    # SMTP login (optional).
    smtp_user: str | None = None
    # SMTP password (optional).
    smtp_password: str | None = None
    # From address on platform mail.
    smtp_from: str = "mebot <no-reply@localhost>"
    # Hard caps per tenant: owners can lower their limits, never raise them above these.
    hosted_max_daily_messages: int = 500
    # Daily token budget cap per tenant (a tenant can't switch it off).
    hosted_max_daily_tokens: int = 1_000_000
    # Messages per visitor chat.
    hosted_max_session_messages: int = 40
    # Messages per visitor IP per day.
    hosted_max_ip_per_day: int = 100
    # Import uploads per tenant per day (one import runs at a time per tenant).
    hosted_max_imports_per_day: int = 10
    # Largest import upload per tenant, in bytes.
    hosted_max_upload_bytes: int = 5_000_000

    @model_validator(mode="after")
    def _registry_url(self) -> "Settings":
        url = self.registry_url.strip().rstrip("/")
        if not url.startswith(("http://", "https://")) or " " in url:
            raise ValueError("REGISTRY_URL must be an http(s) URL")
        self.registry_url = url
        return self

    @model_validator(mode="after")
    def _default_db(self) -> "Settings":
        if not self.database_url:
            self.database_url = f"sqlite:///{(self.data_dir / 'mebot.db').as_posix()}"
        if not self.secret_key:
            self.secret_key = None
        return self

    @property
    def hosted(self) -> bool:
        return self.mode == "hosted"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


def ensure_data_dir(settings: Settings) -> None:
    """Create the data dir and check it is writable, or raise a clear ConfigError."""
    d = settings.data_dir
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".write-test"
        probe.write_text("ok")
        probe.unlink()
    except OSError as e:
        raise ConfigError(
            f"data directory {d} is missing or not writable ({e.strerror or e}). "
            "Create it, fix its permissions (Docker: chown -R 10001:10001 the host dir "
            "mounted at /data), or set DATA_DIR."
        ) from e


def check_database(settings: Settings) -> None:
    """Hosted mode serves many tenants: SQLite's single writer is not enough."""
    if not settings.hosted or not settings.database_url.startswith("sqlite"):
        return
    if not settings.allow_sqlite_hosted:
        raise ConfigError(
            "MODE=hosted needs Postgres: set DATABASE_URL=postgresql+psycopg://user:pass@host/db "
            "(or ALLOW_SQLITE_HOSTED=1 for local development only)."
        )
    logging.getLogger("mebot").warning(
        "MODE=hosted on SQLite (ALLOW_SQLITE_HOSTED=1): development only, not for production."
    )


def resolve_secret_key(settings: Settings) -> str:
    """Return SECRET_KEY; in single mode generate + persist one if unset."""
    if settings.secret_key:
        return settings.secret_key
    if settings.mode == "hosted":
        raise ConfigError("SECRET_KEY must be set when MODE=hosted.")
    path = settings.data_dir / "secret.key"
    if path.exists():
        key = path.read_text(encoding="utf-8").strip()
        if key:
            return key
    ensure_data_dir(settings)
    key = secrets.token_urlsafe(48)
    path.write_text(key, encoding="utf-8")
    return key


def settings_markdown() -> str:
    """docs/configuration.md, generated from the Settings fields and the comments above
    them (``python -m mebot.config --markdown``). CI fails if the checked-in doc drifts."""
    import ast
    import inspect

    src = inspect.getsource(Settings)
    lines = src.splitlines()
    rows = []
    for node in ast.parse(src).body[0].body:
        if not (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)):
            continue
        name = node.target.id
        if name == "model_config":
            continue
        notes, i = [], node.lineno - 2
        while i >= 0 and lines[i].strip().startswith("#"):
            notes.insert(0, lines[i].strip().lstrip("#").strip())
            i -= 1
        default = Settings.model_fields[name].default
        if isinstance(default, Path):
            default = default.relative_to(REPO_ROOT).as_posix()
        shown = (
            "*(unset)*"
            if default in (None, "")
            else f"`{str(default).lower() if isinstance(default, bool) else default}`"
        )
        rows.append(f"| `{name.upper()}` | {shown} | {' '.join(notes)} |")
    head = [
        "# Configuration",
        "",
        "<!-- Generated by `python -m mebot.config --markdown`; do not edit by hand. -->",
        "",
        "All settings are environment variables (or lines in `.env`). In the Docker image",
        "`DATA_DIR=/data` and `FRONTEND_DIST=/app/static` are preset.",
        "",
        "| Variable | Default | Notes |",
        "| --- | --- | --- |",
    ]
    return "\n".join(head + rows) + "\n"


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["--markdown"]:
        sys.stdout.buffer.write(settings_markdown().encode())
    else:
        sys.exit("usage: python -m mebot.config --markdown")
