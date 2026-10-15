"""Cloudflare Turnstile server-side verification (optional, for POST /api/session)."""

import httpx

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TIMEOUT = 5.0


class TurnstileUnavailable(Exception):
    """Cloudflare could not be reached; callers fail closed."""


async def verify(secret_key: str, token: str, ip: str | None) -> bool:
    data = {"secret": secret_key, "response": token}
    if ip:
        data["remoteip"] = ip
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.post(VERIFY_URL, data=data)
            r.raise_for_status()
            return r.json().get("success") is True
    except Exception as e:  # noqa: BLE001 - never echo the secret or Cloudflare's body
        raise TurnstileUnavailable(type(e).__name__) from None


def active(settings, limits) -> bool:
    """Required only when the owner enabled it AND both env keys are set."""
    return bool(
        limits.turnstile_enabled and settings.turnstile_site_key and settings.turnstile_secret_key
    )
