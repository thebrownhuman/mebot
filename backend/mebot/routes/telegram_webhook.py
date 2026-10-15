"""Telegram → us, when the owner picked webhook mode (needs PUBLIC_URL)."""

import secrets

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from mebot.db import get_db
from mebot.errors import ApiError
from mebot.telegram import repo
from mebot.telegram.updates import handle_update

router = APIRouter(prefix="/api/telegram")

SECRET_HEADER = "x-telegram-bot-api-secret-token"


@router.post("/webhook/{bot_id}")
async def webhook(bot_id: str, request: Request, db: Session = Depends(get_db)):
    row = repo.get(db, bot_id)
    given = request.headers.get(SECRET_HEADER) or ""
    if (
        row is None
        or row.mode != "webhook"
        or not row.webhook_secret
        or not secrets.compare_digest(given.encode(), row.webhook_secret.encode())
    ):
        raise ApiError(403, "FORBIDDEN", "Forbidden")
    try:
        update = await request.json()
    except ValueError:
        return {}
    uid = update.get("update_id") if isinstance(update, dict) else None
    if not isinstance(uid, int) or (row.last_update_id is not None and uid <= row.last_update_id):
        return {}  # Telegram retries deliveries; each update is handled once
    row.last_update_id = uid
    db.commit()
    db.close()
    await handle_update(request.app.state.telegram_ctx, bot_id, update)
    return {}
