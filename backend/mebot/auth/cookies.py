"""Auth cookies: HttpOnly session cookie + readable double-submit CSRF cookie."""

from fastapi import Request, Response

from mebot.auth.csrf import CSRF_COOKIE, new_csrf_token
from mebot.config import Settings
from mebot.repos.admin_sessions import TTL

SESSION_COOKIE = "mebot_session"
_MAX_AGE = int(TTL.total_seconds())


def is_secure(request: Request, settings: Settings) -> bool:
    if settings.cookie_secure or request.url.scheme == "https":
        return True
    if settings.trust_proxy:
        proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
        return proto == "https"
    return False


def set_csrf_cookie(response: Response, request: Request, settings: Settings) -> None:
    response.set_cookie(
        CSRF_COOKIE,
        new_csrf_token(),
        max_age=_MAX_AGE,
        path="/",
        samesite="lax",
        secure=is_secure(request, settings),
        httponly=False,  # the frontend reads it and echoes it in X-CSRF-Token
    )


def set_login_cookies(response: Response, request: Request, settings: Settings, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=_MAX_AGE,
        path="/",
        samesite="lax",
        secure=is_secure(request, settings),
        httponly=True,
    )
    set_csrf_cookie(response, request, settings)


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", samesite="lax", httponly=True)


# For error responses raised as exceptions (no Response object to call delete_cookie on).
CLEAR_SESSION_HEADER = f"{SESSION_COOKIE}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax"
