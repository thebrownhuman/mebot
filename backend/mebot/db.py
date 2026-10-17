"""Engine / session plumbing and programmatic Alembic upgrades."""

from collections.abc import Iterator

from alembic import command
from alembic.config import Config
from fastapi import Request
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from mebot.config import BACKEND_DIR


def make_engine(url: str) -> Engine:
    kwargs = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()

    return engine


def make_session_factory(url_or_engine: str | Engine) -> sessionmaker[Session]:
    engine = make_engine(url_or_engine) if isinstance(url_or_engine, str) else url_or_engine
    return sessionmaker(bind=engine, expire_on_commit=False)


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def run_migrations(url: str, secret_key: str | None = None) -> None:
    """Upgrade to head. ``secret_key`` feeds data migrations that hash values (0016);
    when omitted they resolve it from Settings only if there is data to hash."""
    cfg = alembic_config(url)
    cfg.attributes["secret_key"] = secret_key
    command.upgrade(cfg, "head")


def get_db(request: Request) -> Iterator[Session]:
    db = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()
