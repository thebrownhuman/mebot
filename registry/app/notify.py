"""Maintainer notifications over Telegram: a small DB outbox plus the weekly summary and
the ``/stats`` command (answered only in the maintainer's chat)."""

import asyncio
import html
import logging
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from app import stats
from app.config import Settings
from app.db import Database, iso

log = logging.getLogger("registry.notify")

MAX_ATTEMPTS = 8
MAX_TEXT = 3500
BATCH = 20
LOOP_SECONDS = 15


def esc(value: str | None, limit: int = 300) -> str:
    return html.escape((value or "")[:limit], quote=False)


def enqueue(db: Database, settings: Settings, kind: str, text: str, now: datetime) -> bool:
    """Queue a message for the maintainer. No-op when Telegram isn't configured."""
    if not settings.telegram_on:
        return False
    with db.tx() as c:
        c.execute(
            "INSERT INTO notifications (id, kind, text, status, attempts, next_attempt_at,"
            " created_at, updated_at) VALUES (?, ?, ?, 'pending', 0, ?, ?, ?)",
            (str(uuid.uuid4()), kind, text[:MAX_TEXT], iso(now), iso(now), iso(now)),
        )
    return True


def registration_text(kind: str, email: str, site_url: str, version: str) -> str:
    head = "🆕 mebot install" if kind == "new" else "✏️ mebot registration updated"
    return f"{head} — {esc(email)} · {esc(site_url)} · v{esc(version, 40)}"


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def summary_text(title: str, s: dict) -> str:
    versions = ", ".join(f"{esc(v, 40)} ×{n}" for v, n in s["by_version"].items()) or "none yet"
    return "\n".join(
        [
            f"<b>{esc(title)}</b>",
            f"Active installs: {s['active_7d']} (7 days) · {s['active_30d']} (30 days)",
            f"New installs this week: {s['new_installs_7d']}",
            f"Registrations: {s['registrations']} (+{s['new_registrations_7d']} this week)",
            f"Versions (7 days): {versions}",
        ]
    )


def maybe_weekly_summary(db: Database, settings: Settings, now: datetime) -> bool:
    """Queue the summary once per ISO week, from Monday 09:00 in the maintainer's zone."""
    local = now.astimezone(_zone(settings.timezone))
    if local.weekday() != 0 or local.hour < 9:
        return False
    iso_year, iso_week, _ = local.isocalendar()
    key = f"{iso_year}-W{iso_week:02d}"
    if db.meta_get("last_summary_week") == key:
        return False
    db.meta_set("last_summary_week", key)  # mark first so a crash never double-sends
    title = f"📊 mebot weekly — {local.date().isoformat()}"
    return enqueue(db, settings, "weekly", summary_text(title, stats.compute(db, now)), now)


def handle_update(db: Database, settings: Settings, update: dict, now: datetime) -> bool:
    """Answer ``/stats`` — only from the configured maintainer chat."""
    msg = update.get("message") or {}
    if str((msg.get("chat") or {}).get("id")) != str(settings.telegram_chat_id):
        return False
    command = (msg.get("text") or "").strip().split("@")[0].lower()
    if command != "/stats":
        return False
    return enqueue(
        db, settings, "stats", summary_text("📊 mebot stats", stats.compute(db, now)), now
    )


# --- delivery --------------------------------------------------------------------------


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(3600, 30 * 2**attempts))


async def send_due(
    db: Database, settings: Settings, client: httpx.AsyncClient, now: datetime
) -> int:
    """Send pending messages that are due. Returns how many were delivered."""
    if not settings.telegram_on:
        return 0
    with db.tx() as c:
        due = c.execute(
            "SELECT id, text, attempts FROM notifications WHERE status = 'pending'"
            " AND next_attempt_at <= ? ORDER BY created_at LIMIT ?",
            (iso(now), BATCH),
        ).fetchall()
    sent = 0
    url = f"{settings.telegram_api}/bot{settings.telegram_bot_token}/sendMessage"
    for row in due:
        status, next_at, error = "sent", None, None
        attempts = row["attempts"] + 1
        try:
            r = await client.post(
                url,
                json={
                    "chat_id": settings.telegram_chat_id,
                    "text": row["text"],
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            body = r.json() if r.content else {}
            if r.status_code == 200 and body.get("ok", True):
                sent += 1
            elif r.status_code == 429:
                wait = int((body.get("parameters") or {}).get("retry_after") or 30)
                status, next_at, error = "pending", now + timedelta(seconds=max(1, wait)), "rate"
            elif 400 <= r.status_code < 500:  # bad token / chat: retrying cannot help
                status, error = "dead", f"HTTP {r.status_code}: {body.get('description', '')}"[:200]
            else:
                raise httpx.HTTPError(f"HTTP {r.status_code}")
        except (httpx.HTTPError, ValueError) as e:
            error = type(e).__name__
            if attempts >= MAX_ATTEMPTS:
                status = "dead"
            else:
                status, next_at = "pending", now + _backoff(attempts)
        with db.tx() as c:
            c.execute(
                "UPDATE notifications SET status = ?, attempts = ?, next_attempt_at = ?,"
                " last_error = ?, updated_at = ? WHERE id = ?",
                (status, attempts, iso(next_at or now), error, iso(now), row["id"]),
            )
    return sent


async def poll_commands(
    db: Database, settings: Settings, client: httpx.AsyncClient, now: datetime
) -> int:
    """Fetch pending Telegram updates (long-poll off) and answer maintainer commands."""
    if not settings.telegram_on:
        return 0
    offset = db.meta_get("telegram_offset")
    params: dict = {"timeout": 0, "allowed_updates": ["message"]}
    if offset:
        params["offset"] = int(offset)
    url = f"{settings.telegram_api}/bot{settings.telegram_bot_token}/getUpdates"
    try:
        r = await client.post(url, json=params, timeout=10)
        updates = (r.json() or {}).get("result") or []
    except (httpx.HTTPError, ValueError):
        return 0
    handled = 0
    for u in updates:
        if handle_update(db, settings, u, now):
            handled += 1
        db.meta_set("telegram_offset", str(int(u["update_id"]) + 1))
    return handled


async def worker(app) -> None:
    """Outbox delivery, weekly summary, command polling and the daily purge."""
    from app import purge

    settings: Settings = app.state.settings
    db: Database = app.state.db
    last_purge = ""
    async with httpx.AsyncClient() as client:
        while True:
            try:
                now = app.state.clock()
                maybe_weekly_summary(db, settings, now)
                await poll_commands(db, settings, client, now)
                await send_due(db, settings, client, now)
                today = iso(now)[:10]
                if today != last_purge:
                    purge.run(db, settings, now)
                    last_purge = today
            except Exception:  # the loop must outlive any single failure
                log.exception("registry worker round failed")
            await asyncio.sleep(LOOP_SECONDS)
