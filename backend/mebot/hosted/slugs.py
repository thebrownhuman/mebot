"""Slug rules for hosted bots (single mode keeps the setup wizard's own rule)."""

import re

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,30})[a-z0-9]$")
RESERVED = frozenset(
    {
        "admin", "api", "app", "assets", "b", "billing", "blog", "dashboard", "docs",
        "embed", "embed-app", "help", "login", "logout", "mail", "mebot", "platform",
        "reset", "root", "settings", "setup", "signup", "static", "status", "support",
        "system", "verify", "widget", "www",
    }
)  # fmt: skip


def slug_error(slug: str) -> str | None:
    """None if slug is acceptable, else a message for the owner."""
    if not SLUG_RE.match(slug) or "--" in slug:
        return "use 3-32 lowercase letters, digits or single hyphens (not at the ends)"
    if slug in RESERVED:
        return f"'{slug}' is reserved"
    return None
