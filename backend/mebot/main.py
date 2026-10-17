"""App factory. Run with: uvicorn mebot.main:app --reload --port 8000"""

import asyncio
import contextlib
import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from mebot import retention
from mebot.config import ConfigError, Settings, ensure_data_dir, resolve_secret_key
from mebot.db import make_session_factory, run_migrations
from mebot.errors import error_body, install_error_handlers
from mebot.hosted.mailer import make_mailer
from mebot.hosted.tenant import TenantMiddleware
from mebot.imports import github_import, linkedin, pipelines, resume  # noqa: F401 - importing registers the runner
from mebot.limits import counters
from mebot.limits.memory import LoginLimiter, SlidingWindowLimiter
from mebot.limits.service import ChatLimiter
from mebot.repos import admin_sessions, import_jobs
from mebot.routes import routers
from mebot.static import mount_frontend
from mebot.telegram import outbox
from mebot.telegram.service import TelegramService
from mebot.telegram.updates import TgContext
from mebot.telemetry import identity
from mebot.telemetry.service import Telemetry
from mebot.widget.frames import frame_headers


def _validation_error(_, exc: RequestValidationError):
    details = [
        {
            "field": ".".join(str(p) for p in err["loc"] if p not in ("body", "query", "path")),
            "message": err["msg"].removeprefix("Value error, "),
        }
        for err in exc.errors()
    ]
    return JSONResponse(
        error_body(422, "VALIDATION_ERROR", "Invalid request", details), status_code=422
    )


RETENTION_EVERY = 24 * 3600


async def _retention_loop(factory) -> None:
    """Daily purge; the startup purge runs in create_app."""
    while True:
        await asyncio.sleep(RETENTION_EVERY)
        try:
            await asyncio.to_thread(retention.purge_all_bots, factory)
        except Exception:  # a failed purge must not take the app down; retry next round
            logging.getLogger("mebot.retention").exception("retention purge failed")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    ensure_data_dir(settings)
    secret_key = resolve_secret_key(settings)
    install_key = identity.load_or_create(settings.data_dir)
    run_migrations(settings.database_url, secret_key)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Poller / outbox / digest workers; off in tests unless a test turns them on.
        if settings.telegram_workers:
            await app.state.telegram.start()
        purge_task = asyncio.create_task(_retention_loop(app.state.session_factory))
        # Only with TELEMETRY=on: otherwise nothing is scheduled and no request is ever made.
        telemetry = app.state.telemetry
        tele_task = (
            asyncio.create_task(telemetry.worker())
            if telemetry.enabled and settings.telemetry_workers
            else None
        )
        try:
            yield
        finally:
            for task in (purge_task, tele_task):
                if task is not None:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
            await app.state.telegram.stop()

    app = FastAPI(title="me-bot", lifespan=lifespan)
    app.state.settings = settings
    app.state.secret_key = secret_key
    app.state.install_key = install_key
    app.state.session_factory = make_session_factory(settings.database_url)
    app.state.login_limiter = LoginLimiter()
    app.state.chat_limiter = ChatLimiter(secret_key)
    app.state.setup_limiter = SlidingWindowLimiter(limit=10, window_seconds=15 * 60)
    # Recruiter UI polls for owner replies every 5s while visible.
    app.state.updates_limiter = SlidingWindowLimiter(limit=20, window_seconds=60)
    # Recruiter UI fetches the Contact panel once per chat open.
    app.state.channels_limiter = SlidingWindowLimiter(limit=30, window_seconds=60)
    app.state.contact_limiter = SlidingWindowLimiter(limit=3, window_seconds=3600)
    # Imports: 10 uploads per hour per bot; runners by kind (tests swap them).
    app.state.import_limiter = SlidingWindowLimiter(limit=10, window_seconds=3600)
    app.state.import_runners = pipelines.RUNNERS
    # Hosted: imports per tenant per day (limit from HOSTED_MAX_IMPORTS_PER_DAY).
    app.state.import_day_limiter = SlidingWindowLimiter(limit=10, window_seconds=86400)
    app.state.mailer = make_mailer(settings)
    # Hosted sign-up / mail endpoints, per hashed IP and bucket.
    app.state.account_limiter = SlidingWindowLimiter(limit=5, window_seconds=3600)
    app.state.telemetry = Telemetry(settings, app.state.session_factory, install_key)
    app.state.telegram_ctx = TgContext(app.state.session_factory, secret_key, settings)
    app.state.telegram = TelegramService(app.state.telegram_ctx)
    with app.state.session_factory() as db:
        admin_sessions.purge_expired(db)
        counters.purge(db)
        outbox.purge(db)
        import_jobs.purge_expired(db)
        db.commit()
    retention.purge_all_bots(app.state.session_factory)
    install_error_handlers(app)
    app.add_exception_handler(RequestValidationError, _validation_error)
    # Inside CORS: rewrites /b/{ref}/... and picks the tenant (hosted mode).
    app.add_middleware(
        TenantMiddleware, settings=settings, session_factory=app.state.session_factory
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Outermost, so error responses and CORS preflights carry the frame headers too.
    app.middleware("http")(frame_headers)
    for r in routers:
        app.include_router(r)
    # Last, so its catch-all GET never shadows an API route.
    mount_frontend(app, settings.frontend_dist)
    return app


def __getattr__(name: str):
    # Build `app` lazily so importing this module (tests, tooling) has no side effects,
    # and turn configuration errors into a one-line message instead of a traceback.
    if name == "app":
        try:
            application = create_app()
        except ConfigError as e:
            print(f"mebot: configuration error: {e}", file=sys.stderr)
            raise SystemExit(1) from None
        globals()["app"] = application
        return application
    raise AttributeError(name)
