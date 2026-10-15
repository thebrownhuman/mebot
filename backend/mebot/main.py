"""App factory. Run with: uvicorn mebot.main:app --reload --port 8000"""

import sys

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from mebot.config import ConfigError, Settings, ensure_data_dir, resolve_secret_key
from mebot.db import make_session_factory, run_migrations
from mebot.errors import error_body, install_error_handlers
from mebot.limits import counters
from mebot.limits.memory import LoginLimiter, SlidingWindowLimiter
from mebot.limits.service import ChatLimiter
from mebot.repos import admin_sessions
from mebot.routes import routers


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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    ensure_data_dir(settings)
    secret_key = resolve_secret_key(settings)
    run_migrations(settings.database_url)

    app = FastAPI(title="me-bot")
    app.state.settings = settings
    app.state.secret_key = secret_key
    app.state.session_factory = make_session_factory(settings.database_url)
    app.state.login_limiter = LoginLimiter()
    app.state.chat_limiter = ChatLimiter(secret_key)
    app.state.setup_limiter = SlidingWindowLimiter(limit=10, window_seconds=15 * 60)
    with app.state.session_factory() as db:
        admin_sessions.purge_expired(db)
        counters.purge(db)
        db.commit()
    install_error_handlers(app)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    for r in routers:
        app.include_router(r)
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
