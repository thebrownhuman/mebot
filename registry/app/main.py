"""mebot install registry: signed heartbeats, opt-in registrations, release info."""

import asyncio
import contextlib
import hmac
import json
import re
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app import notify, stats
from app.auth import AuthError, Verified, verify_signed
from app.config import Settings
from app.db import Database, iso
from app.limits import DailyCounter, SlidingWindow
from app.releases import ReleasesFile

_VERSION = re.compile(r"^\d{1,4}\.\d{1,4}\.\d{1,4}([-+][0-9A-Za-z.+-]{1,30})?$")
_MODE = re.compile(r"^[a-z][a-z_-]{0,15}$")
_EMAIL = re.compile(r"^[^@\s<>]{1,64}@[^@\s<>]{1,190}\.[^@\s<>]{2,}$")
_HEX32 = re.compile(r"^[0-9a-f]{32}$")


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        headers: dict | None = None,
        details: list | None = None,
    ):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.headers, self.details = headers, details


def error_body(status: int, code: str, message: str, details: list | None = None) -> dict:
    body = {"code": code, "message": message, "status": status}
    if details:
        body["details"] = details
    return {"error": body}


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    install_id: str
    public_key: str = Field(min_length=40, max_length=48)
    version: str = Field(max_length=40)

    @field_validator("install_id")
    @classmethod
    def _id(cls, v: str) -> str:
        v = v.lower()
        if not _HEX32.match(v):
            raise ValueError("install_id must be 32 hex characters")
        return v

    @field_validator("version")
    @classmethod
    def _version(cls, v: str) -> str:
        if not _VERSION.match(v):
            raise ValueError("version must look like 1.2.3")
        return v


class Heartbeat(_Base):
    mode: str

    @field_validator("mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        if not _MODE.match(v):
            raise ValueError("invalid mode")
        return v


class Register(_Base):
    email: str = Field(max_length=254)
    site_url: str = Field(max_length=300)
    bot_name: str | None = Field(default=None, max_length=80)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        if not _EMAIL.match(v):
            raise ValueError("not a valid e-mail address")
        local, _, domain = v.rpartition("@")
        return f"{local}@{domain.lower()}"

    @field_validator("site_url")
    @classmethod
    def _site(cls, v: str) -> str:
        parts = urlsplit(v)
        if parts.scheme not in ("http", "https") or not parts.hostname or re.search(r"\s", v):
            raise ValueError("site_url must be an http(s) URL")
        return v


def create_app(
    settings: Settings | None = None, clock: Callable[[], datetime] | None = None
) -> FastAPI:
    settings = settings or Settings.from_env()
    db = Database(settings.db_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(notify.worker(app)) if settings.workers else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title="mebot registry", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.db = db
    app.state.clock = clock or (lambda: datetime.now(UTC))
    app.state.releases = ReleasesFile(settings.releases_path)
    app.state.limiters = {
        "heartbeat": SlidingWindow(*settings.heartbeat_limit),
        "register": SlidingWindow(*settings.register_limit),
        "delete": SlidingWindow(*settings.delete_limit),
    }
    app.state.new_installs = DailyCounter(settings.new_installs_per_ip_per_day)

    @app.exception_handler(ApiError)
    async def _api_error(_, e: ApiError):
        return JSONResponse(
            error_body(e.status, e.code, e.message, e.details),
            status_code=e.status,
            headers=e.headers,
        )

    @app.exception_handler(AuthError)
    async def _auth_error(_, e: AuthError):
        return JSONResponse(error_body(e.status, e.code, e.message), status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_, e: RequestValidationError):
        return JSONResponse(error_body(422, "VALIDATION_ERROR", "Invalid request"), status_code=422)

    # --- helpers -------------------------------------------------------------------------

    def client_ip(request: Request) -> str:
        if settings.trust_proxy:
            fwd = request.headers.get("x-forwarded-for", "")
            if fwd.strip():
                return fwd.split(",")[0].strip()
        return request.client.host if request.client else "?"

    def limited(scope: str, request: Request) -> None:
        wait = app.state.limiters[scope].hit(client_ip(request))
        if wait is not None:
            raise ApiError(429, "RATE_LIMITED", "Too many requests.", {"Retry-After": str(wait)})

    async def read_body(request: Request) -> bytes:
        cap = settings.max_body_bytes
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > cap:
            raise ApiError(413, "BODY_TOO_LARGE", "Request body is too large.")
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > cap:
                raise ApiError(413, "BODY_TOO_LARGE", "Request body is too large.")
            chunks.append(chunk)
        return b"".join(chunks)

    def parse(model: type[BaseModel], body: bytes):
        try:
            return model.model_validate(json.loads(body or b"null"))
        except ValidationError as e:
            details = [
                {"field": ".".join(str(p) for p in err["loc"]), "message": err["msg"]}
                for err in e.errors()
            ]
            raise ApiError(422, "VALIDATION_ERROR", "Invalid request.", details=details) from None
        except ValueError:
            raise ApiError(422, "VALIDATION_ERROR", "Body must be JSON.") from None

    def verified_for(request: Request, body: bytes, model: _Base | None, now: datetime) -> Verified:
        v = verify_signed(
            headers=request.headers,
            method=request.method,
            path=request.url.path,
            body=body,
            db=db,
            now=now,
            claimed_key=model.public_key if model else None,
        )
        if model and model.install_id != v.install_id:
            raise AuthError("SIGNATURE_INVALID", "Install id does not match the signature.")
        return v

    def admit_new_install(request: Request, v: Verified, now: datetime) -> None:
        if not v.is_new:
            return
        ip, today = client_ip(request), now.date()
        if not app.state.new_installs.allow(ip, today):
            raise ApiError(429, "TOO_MANY_INSTALLS", "Too many new installs from this address.")
        app.state.new_installs.add(ip, today)

    def upsert_install(c, v: Verified, version: str, mode: str | None, now: datetime) -> None:
        stamp = iso(now)
        c.execute(
            "INSERT INTO installs (install_id, public_key, first_seen, last_seen, version, mode)"
            " VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(install_id) DO UPDATE SET"
            " last_seen = excluded.last_seen, version = excluded.version,"
            " mode = COALESCE(?, installs.mode)",
            (v.install_id, v.public_key, stamp, stamp, version, mode or "single", mode),
        )

    # --- endpoints -----------------------------------------------------------------------

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.post("/v1/heartbeat", status_code=204)
    async def heartbeat(request: Request):
        limited("heartbeat", request)
        now = app.state.clock()
        body = await read_body(request)
        data = parse(Heartbeat, body)
        v = verified_for(request, body, data, now)
        admit_new_install(request, v, now)
        with db.tx() as c:
            upsert_install(c, v, data.version, data.mode, now)
        return Response(status_code=204)

    @app.post("/v1/register")
    async def register(request: Request):
        limited("register", request)
        now = app.state.clock()
        body = await read_body(request)
        data = parse(Register, body)
        v = verified_for(request, body, data, now)
        domain = data.email.rpartition("@")[2]
        if data.email.lower() in settings.blocklist or domain in settings.blocklist:
            raise ApiError(403, "REGISTRATION_BLOCKED", "This address can't be registered.")
        admit_new_install(request, v, now)
        stamp = iso(now)
        with db.tx() as c:
            upsert_install(c, v, data.version, None, now)
            row = c.execute(
                "SELECT email, site_url FROM registrations WHERE install_id = ?", (v.install_id,)
            ).fetchone()
            if row is None:
                c.execute(
                    "INSERT INTO registrations (id, install_id, email, site_url, bot_name, version,"
                    " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid.uuid4()),
                        v.install_id,
                        data.email,
                        data.site_url,
                        data.bot_name,
                        data.version,
                        stamp,
                        stamp,
                    ),
                )
                kind = "new"
            else:
                c.execute(
                    "UPDATE registrations SET email = ?, site_url = ?, bot_name = ?, version = ?,"
                    " updated_at = ? WHERE install_id = ?",
                    (data.email, data.site_url, data.bot_name, data.version, stamp, v.install_id),
                )
                changed = (row["email"], row["site_url"]) != (data.email, data.site_url)
                kind = "updated" if changed else "unchanged"
        if kind != "unchanged":
            notify.enqueue(
                db,
                settings,
                f"registration_{kind}",
                notify.registration_text(kind, data.email, data.site_url, data.version),
                now,
            )
        return JSONResponse({"status": kind}, status_code=201 if kind == "new" else 200)

    @app.delete("/v1/register", status_code=204)
    async def unregister(request: Request):
        limited("delete", request)
        now = app.state.clock()
        body = await read_body(request)
        v = verified_for(request, body, None, now)
        with db.tx() as c:
            c.execute("DELETE FROM registrations WHERE install_id = ?", (v.install_id,))
        return Response(status_code=204)

    @app.get("/v1/latest")
    def latest():
        return app.state.releases.get().model_dump()

    @app.get("/v1/stats")
    def get_stats(request: Request):
        token = request.headers.get("authorization", "")
        expected = f"Bearer {settings.admin_token}"
        if not settings.admin_token or not hmac.compare_digest(token, expected):
            raise ApiError(401, "UNAUTHORIZED", "Maintainer token required.")
        return stats.compute(db, app.state.clock())

    return app


def __getattr__(name: str):
    if name == "app":
        application = create_app()
        globals()["app"] = application
        return application
    raise AttributeError(name)
