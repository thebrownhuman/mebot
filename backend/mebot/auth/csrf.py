"""CSRF: double-submit cookie (required) plus an Origin/Referer allow-list check."""

import secrets
from urllib.parse import urlsplit

from fastapi import Request

from mebot.errors import ApiError

CSRF_COOKIE = "mebot_csrf"
CSRF_HEADER = "X-CSRF-Token"


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def _origin_of(url: str) -> str | None:
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}".lower()


def _origin_allowed(request: Request, origin: str) -> bool:
    allowed = {o.rstrip("/").lower() for o in request.app.state.settings.cors_origin_list}
    if origin in allowed:
        return True
    # Same host as this request (scheme may differ behind a TLS-terminating proxy).
    host = request.headers.get("host", "").lower()
    return bool(host) and urlsplit(origin).netloc == host


def _fail(message: str) -> ApiError:
    return ApiError(403, "CSRF_FAILED", message)


def require_csrf(request: Request) -> None:
    source = request.headers.get("origin") or request.headers.get("referer")
    if source:
        origin = _origin_of(source)
        if origin is None or not _origin_allowed(request, origin):
            raise _fail("Cross-origin request blocked")

    cookie = request.cookies.get(CSRF_COOKIE, "")
    header = request.headers.get(CSRF_HEADER, "")
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise _fail("Missing or invalid CSRF token")
