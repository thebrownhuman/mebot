"""Runtime configuration. Everything comes from env vars (or a .env file)."""

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

    mode: Literal["single", "hosted"] = "single"
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
    turnstile_secret_key: str | None = None
    # Public base URL (https://bot.example.com). Enables the Telegram webhook option and
    # "Open chat" links in notifications.
    public_url: str | None = None
    # Background Telegram tasks (poller, outbox, digest). Tests turn them off.
    telegram_workers: bool = True
    # Built frontend (npm run build). The backend serves the widget loader and the embed
    # bundle from here when nginx doesn't (single-process / dev setups).
    frontend_dist: Path = REPO_ROOT / "frontend" / "dist"
    # Optional token for GitHub imports (public data only; raises the 60/hour limit).
    # A token saved in Admin -> Import takes precedence.
    github_token: str | None = None

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
            "Create it, fix its permissions, or set DATA_DIR."
        ) from e


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
