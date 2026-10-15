"""Long-polling getUpdates loop, guarded by a DB lease so one process polls per bot.

Two app processes (or uvicorn --reload's parent and child) would otherwise both call
getUpdates and Telegram answers one of them with 409; worse, both could handle the
same update. The lease is a row-level compare-and-set on telegram_configs with a
heartbeat (renewed every poll); a crashed holder's lease simply expires.
"""

import asyncio
import logging
from datetime import timedelta

from mebot.repos import logs
from mebot.telegram import repo
from mebot.telegram.client import TelegramError
from mebot.telegram.updates import TgContext, handle_update

log = logging.getLogger(__name__)

LEASE_TTL = timedelta(seconds=60)  # > one getUpdates long-poll (25s) + margin
MIN_BACKOFF = 1.0
MAX_BACKOFF = 60.0


def next_backoff(current: float) -> float:
    return MIN_BACKOFF if current <= 0 else min(MAX_BACKOFF, current * 2)


async def poll_once(ctx: TgContext, bot_id: str, owner: str, timeout: int = 25) -> str:
    """One getUpdates round. Returns "ok", "no_lease", "inactive", "auth" or "error"."""
    with ctx.session_factory() as db:
        row = repo.get(db, bot_id)
        client = repo.client_for(row, ctx.secret_key)
        if row is None or client is None or row.mode != "polling" or not row.enabled:
            return "inactive"
        if not repo.try_lease(db, bot_id, owner, LEASE_TTL, ctx.now()):
            return "no_lease"
        offset = row.last_update_id + 1 if row.last_update_id is not None else None
    try:
        updates = await client.get_updates(offset=offset, timeout=timeout)
    except TelegramError as e:
        if e.kind == "auth":
            with ctx.session_factory() as db:
                row = repo.get(db, bot_id)
                if row is not None and row.error is None:
                    row.error = "Telegram rejected the bot token (revoked?). Paste a new one."
                    logs.add(db, bot_id, None, "TELEGRAM_AUTH_FAILED")
                    db.commit()
            return "auth"
        log.warning("telegram getUpdates failed: %s", e.message)
        return "error"
    for update in sorted(updates, key=lambda u: u.get("update_id", 0)):
        uid = update.get("update_id")
        try:
            await handle_update(ctx, bot_id, update)
        except Exception:  # noqa: BLE001 - one bad update must not wedge the loop
            log.exception("telegram update %s failed", uid)
        # Persist after each update so a crash never replays handled ones.
        with ctx.session_factory() as db:
            row = repo.get(db, bot_id)
            if row is not None and uid is not None:
                row.last_update_id = max(uid, row.last_update_id or 0)
                db.commit()
    return "ok"


async def run_poller(ctx: TgContext, bot_id: str, owner: str, stop: asyncio.Event) -> None:
    """Poll until stopped, the token is rejected, or the bot leaves polling mode."""
    with ctx.session_factory() as db:
        client = repo.client_for(repo.get(db, bot_id), ctx.secret_key)
    if client is not None:
        try:  # switching from webhook: Telegram refuses getUpdates while one is set
            await client.delete_webhook()
        except TelegramError as e:
            log.warning("deleteWebhook failed: %s", e.message)
    backoff = 0.0
    try:
        while not stop.is_set():
            status = await poll_once(ctx, bot_id, owner)
            if status in ("auth", "inactive"):
                return
            if status == "ok":
                backoff = 0.0
                continue
            # no_lease: another process polls; check back later. error: back off.
            backoff = next_backoff(backoff) if status == "error" else LEASE_TTL.total_seconds() / 2
            try:
                await asyncio.wait_for(stop.wait(), timeout=backoff)
            except TimeoutError:
                pass
    finally:
        with ctx.session_factory() as db:
            repo.release_lease(db, bot_id, owner)
