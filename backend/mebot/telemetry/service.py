"""Telemetry jobs: registration, anonymous heartbeat and update check.

``Telemetry.run_due`` does whatever is due right now and never raises: a registry that is
down, slow or hostile must not affect the app. With ``TELEMETRY=off`` it does nothing, so
no request is ever made. Database sessions are never held across a network call.
"""

import asyncio
import json
import logging
import random
from collections.abc import Callable
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from mebot import __version__
from mebot.config import Settings
from mebot.models import Admin, Bot, TelemetryState, utcnow
from mebot.repos import bots
from mebot.telemetry import identity, semver
from mebot.telemetry.client import RegistryClient, RegistryError

log = logging.getLogger("mebot.telemetry")

STARTUP_DELAY = timedelta(minutes=5)
HEARTBEAT_EVERY = timedelta(hours=24)
HEARTBEAT_JITTER = timedelta(hours=1)
RETRY_EVERY = timedelta(minutes=10)
TICK_SECONDS = 30


def get_state(db: Session) -> TelemetryState:
    row = db.scalar(select(TelemetryState).limit(1))
    if row is None:
        row = TelemetryState()
        db.add(row)
        db.flush()
    return row


def _admin_email(db: Session) -> str | None:
    return db.scalar(
        select(Admin.email).where(Admin.deleted_at.is_(None)).order_by(Admin.created_at).limit(1)
    )


def contact_email(db: Session, bot: Bot) -> str | None:
    return (bot.update_contact_email or "").strip() or _admin_email(db)


def fingerprint(email: str, site_url: str, version: str) -> str:
    """What a registration says; when it changes (major version included) we re-register."""
    return f"{email.lower()}|{site_url}|{semver.major(version)}"


def _advisories(state: TelemetryState) -> list[dict]:
    try:
        data = json.loads(state.advisories or "[]")
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def update_info(state: TelemetryState, bot: Bot, current: str = __version__) -> dict:
    """What the admin banners need. The advisory is the first one that matches this version."""
    advisory = next(
        (a for a in _advisories(state) if semver.affected(a.get("affected", ""), current)), None
    )
    latest = state.latest_version
    available = semver.update_available(latest, current)
    return {
        "current": current,
        "latest": latest,
        "available": available,
        "dismissed": bool(available and bot.dismissed_update_version == latest),
        "advisory": advisory,
        "unsupported": bool(
            state.min_supported
            and semver.parse(current)
            and semver.parse(state.min_supported)
            and semver.parse(current) < semver.parse(state.min_supported)
        ),
    }


class Telemetry:
    def __init__(
        self,
        settings: Settings,
        factory: sessionmaker,
        key: identity.InstallKey | None,
        *,
        clock: Callable[[], datetime] = utcnow,
        rng: Callable[[], float] = random.random,
        transport: httpx.AsyncBaseTransport | None = None,
        version: str = __version__,
    ):
        self.settings, self.factory, self.key = settings, factory, key
        self.clock, self.rng, self.transport, self.version = clock, rng, transport, version
        self.next_heartbeat_at: datetime = clock() + STARTUP_DELAY
        self.next_retry_at: datetime | None = None
        self._wake = asyncio.Event()

    # --- switches -------------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self.settings.telemetry == "on" and self.key is not None

    def client(self) -> RegistryClient:
        assert self.key is not None
        return RegistryClient(
            self.settings.registry_url,
            self.key,
            self.version,
            self.settings.mode,
            transport=self.transport,
        )

    def nudge(self) -> None:
        """Consent or contact details changed: retry registration/unregistration now."""
        self.next_retry_at = None
        self._wake.set()

    # --- status (no network) --------------------------------------------------------------

    def desired(self, db: Session, bot: Bot) -> tuple[str, str] | None:
        """(email, site_url) to register with, or None while consent / URL / e-mail is missing."""
        site = (self.settings.public_url or "").strip()
        email = contact_email(db, bot)
        if not (bot.registration_consent and site and email):
            return None
        return email, site

    def status(self, db: Session, bot: Bot) -> str:
        if self.settings.telemetry != "on":
            return "off"
        if self.key is None:
            return "unavailable"
        st = get_state(db)
        if st.unregister_pending:
            return "unregister_pending"
        if not bot.registration_consent:
            return "not_registered"
        want = self.desired(db, bot)
        if want is None:
            return "waiting_for_public_url"
        if st.registered_at and st.registered_fingerprint == fingerprint(*want, self.version):
            return "registered"
        return "pending"

    # --- the work -------------------------------------------------------------------------

    async def run_due(self, now: datetime | None = None) -> None:
        if not self.enabled:
            return
        now = now or self.clock()
        try:
            await self._registration(now)
            if now >= self.next_heartbeat_at:
                await self._heartbeat(now)
        except Exception:  # nothing here may ever reach the app
            log.debug("telemetry round failed", exc_info=True)

    async def _registration(self, now: datetime) -> None:
        if self.next_retry_at is not None and now < self.next_retry_at:
            return
        with self.factory() as db:
            bot = bots.get_primary(db)
            st = get_state(db)
            if bot.registration_consent and st.unregister_pending:
                st.unregister_pending = False  # opted back in before the delete went through
            elif not bot.registration_consent and (
                st.registered_at or st.registered_fingerprint or st.unregister_pending
            ):
                st.unregister_pending = True
            db.commit()
            action: tuple[str, str, str] | None = None
            if st.unregister_pending:
                action = ("unregister", "", "")
            elif (want := self.desired(db, bot)) is not None:
                fp = fingerprint(*want, self.version)
                if st.registered_fingerprint != fp:
                    action = ("register", *want)
        if action is None:
            return
        kind, email, site = action
        error: str | None = None
        try:
            if kind == "unregister":
                try:
                    await self.client().unregister(int(now.timestamp()))
                except RegistryError as e:
                    # Nothing registered under this key: the goal (no registration) is met.
                    if not (e.status == 401 and "UNKNOWN_INSTALL" in str(e)):
                        raise
            else:
                await self.client().register(email, site, int(now.timestamp()))
        except RegistryError as e:
            error = str(e)[:200]
        with self.factory() as db:
            st = get_state(db)
            if error:
                st.last_register_error = error
                self.next_retry_at = now + RETRY_EVERY
            else:
                st.last_register_error = None
                self.next_retry_at = None
                if kind == "unregister":
                    st.registered_at = st.registered_fingerprint = None
                    st.unregister_pending = False
                else:
                    st.registered_at = st.registered_at or now
                    st.registered_fingerprint = fingerprint(email, site, self.version)
            st.updated_at = now
            db.commit()

    async def _heartbeat(self, now: datetime) -> None:
        jitter = (self.rng() * 2 - 1) * HEARTBEAT_JITTER.total_seconds()
        self.next_heartbeat_at = now + HEARTBEAT_EVERY + timedelta(seconds=jitter)
        client = self.client()
        sent = None
        try:
            sent = await client.heartbeat(int(now.timestamp()))
        except RegistryError as e:
            log.debug("heartbeat failed: %s", e)
        latest = None
        try:
            latest = await client.latest()
        except RegistryError as e:
            log.debug("update check failed: %s", e)
        with self.factory() as db:
            st = get_state(db)
            if sent is not None:
                st.last_heartbeat_at = now
                st.last_heartbeat_payload = json.dumps(sent, separators=(",", ":"))
            if latest is not None:
                st.last_check_at = now
                st.latest_version = latest.latest
                st.min_supported = latest.min_supported
                st.advisories = json.dumps([a.model_dump() for a in latest.advisories])
            st.updated_at = now
            db.commit()

    async def worker(self) -> None:
        """Run forever: wake every 30 s (or on a nudge) and do what is due."""
        while True:
            await self.run_due()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=TICK_SECONDS)
            except TimeoutError:
                pass
            self._wake.clear()
