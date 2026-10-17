"""Per-tenant hard caps (hosted mode). Owners may lower their #6 limits, never raise them
above HOSTED_MAX_*; the same value is the default for new tenants. Rows saved before a
cap was lowered are clamped at read time, so the cap always wins."""

from mebot.errors import ApiError

# BotLimits field -> Settings field holding its cap.
CAPS = {
    "daily_message_cap": "hosted_max_daily_messages",
    "daily_token_cap": "hosted_max_daily_tokens",
    "per_session_messages": "hosted_max_session_messages",
    "per_ip_per_day": "hosted_max_ip_per_day",
}


class _Clamped:
    def __init__(self, row, caps: dict[str, int]):
        self._row, self._caps = row, caps

    def __getattr__(self, name):
        value = getattr(self._row, name)
        cap = self._caps.get(name)
        if cap is None:
            return value
        return cap if value is None else min(value, cap)


def caps(settings) -> dict[str, int]:
    return {f: getattr(settings, s) for f, s in CAPS.items()} if settings.hosted else {}


def clamp(row, settings):
    """row in single mode; a read-only clamped view of it in hosted mode."""
    return _Clamped(row, caps(settings)) if settings.hosted else row


def check(values: dict, settings) -> None:
    """422 if an update would raise a limit above (or switch off) its cap."""
    details = []
    for field, cap in caps(settings).items():
        if field in values and (values[field] is None or values[field] > cap):
            details.append({"field": field, "message": f"must be at most {cap} on this server"})
    if details:
        raise ApiError(422, "VALIDATION_ERROR", "Invalid request", details)


def hosted_daily_import_limit(request, bot_id: str) -> None:
    """Hosted: at most HOSTED_MAX_IMPORTS_PER_DAY imports per tenant per day."""
    settings = request.app.state.settings
    if not settings.hosted:
        return
    wait = request.app.state.import_day_limiter.hit(
        bot_id, limit=settings.hosted_max_imports_per_day
    )
    if wait is not None:
        raise ApiError(
            429,
            "RATE_LIMITED",
            "You've reached today's import limit. Please try again tomorrow.",
            headers={"Retry-After": str(wait)},
        )


def upload_cap(request, max_bytes: int) -> int:
    settings = request.app.state.settings
    return min(max_bytes, settings.hosted_max_upload_bytes) if settings.hosted else max_bytes
