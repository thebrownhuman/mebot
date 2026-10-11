"""App factory. Run with: uvicorn mebot.main:app --reload --port 8000"""

import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mebot.config import ConfigError, Settings, ensure_data_dir, resolve_secret_key
from mebot.db import make_session_factory, run_migrations
from mebot.routes import routers


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    ensure_data_dir(settings)
    secret_key = resolve_secret_key(settings)
    run_migrations(settings.database_url)

    app = FastAPI(title="me-bot")
    app.state.settings = settings
    app.state.secret_key = secret_key
    app.state.session_factory = make_session_factory(settings.database_url)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
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
