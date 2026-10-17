"""Registry settings, read from the environment (see .env.example)."""

import os
from dataclasses import dataclass, field
from pathlib import Path


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    data_dir: Path = Path("data")
    releases_path: Path = Path("releases.json")
    admin_token: str = ""  # Bearer token for GET /v1/stats; empty disables the endpoint
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    timezone: str = "Asia/Kolkata"
    blocklist: tuple[str, ...] = ()  # lowercase emails or domains
    trust_proxy: bool = False  # read the client IP from X-Forwarded-For (behind a tunnel/proxy)
    workers: bool = True  # outbox / weekly summary / purge loop (off in tests)
    telegram_api: str = "https://api.telegram.org"
    # Rate limits per client IP: (max requests, window seconds).
    heartbeat_limit: tuple[int, int] = (10, 3600)
    register_limit: tuple[int, int] = (5, 3600)
    delete_limit: tuple[int, int] = (5, 3600)
    new_installs_per_ip_per_day: int = 20
    max_body_bytes: int = 4096
    purge_after_days: int = 180
    extra: dict = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "registry.db"

    @classmethod
    def from_env(cls) -> "Settings":
        block = os.environ.get("REGISTRY_BLOCKLIST", "")
        return cls(
            data_dir=Path(os.environ.get("REGISTRY_DATA_DIR", "data")),
            releases_path=Path(os.environ.get("REGISTRY_RELEASES", "releases.json")),
            admin_token=os.environ.get("REGISTRY_ADMIN_TOKEN", ""),
            telegram_bot_token=os.environ.get("REGISTRY_TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=os.environ.get("REGISTRY_TELEGRAM_CHAT_ID", ""),
            timezone=os.environ.get("REGISTRY_TIMEZONE", "Asia/Kolkata"),
            blocklist=tuple(p.strip().lower() for p in block.split(",") if p.strip()),
            trust_proxy=_flag("REGISTRY_TRUST_PROXY", False),
            workers=_flag("REGISTRY_WORKERS", True),
        )

    @property
    def telegram_on(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)
