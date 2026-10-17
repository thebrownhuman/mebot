"""Which bot a public request is for (hosted mode).

Public pages and APIs live under ``/b/{ref}/...`` where ref is the bot's slug (recruiter
page links) or its public key ``pk_...`` (widget embeds). The middleware strips the
prefix, so the existing routes serve it unchanged, and records the bot in
``scope["state"]["tenant_bot_id"]``. With HOSTED_DOMAIN set, ``{slug}.HOSTED_DOMAIN``
works the same without the prefix.

Only public paths may carry a tenant: admin and account APIs always use the logged-in
owner's bot (see deps.get_current_bot), so ``/b/{other}/api/admin/...`` is a 404.
Unknown, suspended, deleted, not-yet-live and (with paid plans) unpaid bots are all the
same neutral 404.
In single mode ``/b/...`` is always a 404.
"""

import re

import anyio
from starlette.responses import JSONResponse, RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from mebot.billing import service as billing
from mebot.errors import error_body
from mebot.repos import bots

PREFIX_RE = re.compile(r"^/b/([^/]+)(/.*)?$")
# Paths a tenant prefix / subdomain may reach. Everything else under /api is owner-only.
PUBLIC_API = ("/api/public/", "/api/session", "/api/chat", "/api/contact", "/api/health")
NOT_PUBLIC = ("/api/", "/widget-test", "/admin", "/platform")

UNAVAILABLE = "BOT_UNAVAILABLE"


def _is_public(path: str) -> bool:
    if path.startswith(PUBLIC_API) or path == "/api/public":
        return True
    return not path.startswith(NOT_PUBLIC) and path != "/api"


def _not_found() -> JSONResponse:
    return JSONResponse(
        error_body(404, UNAVAILABLE, "This assistant is unavailable."), status_code=404
    )


class TenantMiddleware:
    def __init__(self, app: ASGIApp, settings, session_factory):
        self.app = app
        self.settings = settings
        self.session_factory = session_factory
        domain = (settings.hosted_domain or "").strip().lower().strip(".")
        self.domain_suffix = f".{domain}" if domain else None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        m = PREFIX_RE.match(path)
        if m is None and not (self.settings.hosted and self.domain_suffix):
            return await self.app(scope, receive, send)
        if m is not None and not self.settings.hosted:
            return await _not_found()(scope, receive, send)

        if m is not None:
            ref, rest = m.group(1), m.group(2) or "/"
        else:
            ref, rest = self._subdomain(scope), path
            if ref is None:
                return await self.app(scope, receive, send)

        if not _is_public(rest):
            return await _not_found()(scope, receive, send)
        bot_id, new_slug = await anyio.to_thread.run_sync(self._resolve, ref)
        if new_slug is not None and m is not None:
            query = scope.get("query_string", b"").decode()
            target = f"/b/{new_slug}{'' if rest == '/' else rest}" + (f"?{query}" if query else "")
            return await RedirectResponse(target, status_code=301)(scope, receive, send)
        if bot_id is None:
            if not rest.startswith("/api") and scope["method"] in ("GET", "HEAD"):
                # A page: let the SPA render its neutral "unavailable" screen (its own API
                # calls under /b/{ref} get the JSON 404).
                return await self.app(scope, receive, send)
            return await _not_found()(scope, receive, send)

        scope = dict(scope)
        scope["path"] = rest
        scope["raw_path"] = rest.encode()
        state = dict(scope.get("state") or {})
        state["tenant_bot_id"] = bot_id
        scope["state"] = state
        await self.app(scope, receive, send)

    def _subdomain(self, scope: Scope) -> str | None:
        host = ""
        for k, v in scope.get("headers") or []:
            if k == b"host":
                host = v.decode("latin-1").lower().split(":")[0]
                break
        if not host.endswith(self.domain_suffix):
            return None
        sub = host[: -len(self.domain_suffix)]
        return sub if sub and "." not in sub and sub != "www" else None

    def _resolve(self, ref: str) -> tuple[str | None, str | None]:
        """(bot id, None) for a live bot; (None, new slug) for a renamed one; else (None, None)."""
        with self.session_factory() as db:
            if ref.startswith("pk_"):
                bot = bots.get_live_by_public_key(db, ref)
                return (bot.id if self._serving(db, bot) else None), None
            bot = bots.get_live_by_slug(db, ref)
            if bot is not None:
                return (bot.id if self._serving(db, bot) else None), None
            moved = bots.redirect_target(db, ref)
            return None, (moved.slug if moved else None)

    def _serving(self, db, bot) -> bool:
        return bot is not None and billing.is_serving(db, self.settings, bot.id)
