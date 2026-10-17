"""POST /api/billing/webhook/{provider}: the only way a payment changes a subscription.

raw body -> signature (400, logged without the body) -> billing_events insert (a processed
duplicate is a 200 no-op) -> handle_event in a transaction. A processing error is stored
on the event and answered 500, so the provider retries; the retry runs it again. Unknown
event types are stored and answered 200. 404 unless billing is on for that provider.
"""

import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mebot.billing import service
from mebot.billing.providers import InvalidSignature
from mebot.db import get_db
from mebot.errors import ApiError, error_body
from mebot.hosted import operator
from mebot.llm.base import scrub
from mebot.models import BillingEvent, utcnow

log = logging.getLogger("mebot.billing")
router = APIRouter(prefix="/api/billing")
MAX_BODY = 1_000_000


def _secrets(settings) -> list[str | None]:
    return [
        settings.razorpay_key_id, settings.razorpay_key_secret, settings.razorpay_webhook_secret,
        settings.stripe_secret_key, settings.stripe_webhook_secret,
    ]  # fmt: skip


@router.post("/webhook/{provider}")
async def webhook(
    provider: str,
    request: Request,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
):
    settings = request.app.state.settings
    impl = request.app.state.billing_providers.get(provider)
    if not service.enabled(settings) or impl is None:
        raise ApiError(404, "NOT_FOUND", "Not Found")
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise ApiError(413, "PAYLOAD_TOO_LARGE", "Payload too large")
    try:
        event = impl.verify_webhook(request.headers, raw)
    except (InvalidSignature, ValueError):
        log.warning(
            "billing webhook from %s: invalid signature or body (%d bytes)", provider, len(raw)
        )
        raise ApiError(400, "INVALID_SIGNATURE", "Invalid signature") from None
    ev = impl.parse(event, request.headers, raw)
    if not ev.event_id:
        raise ApiError(400, "INVALID_EVENT", "Event has no id")

    row = BillingEvent(
        provider=provider,
        event_id=ev.event_id,
        type=ev.type,
        bot_id=ev.bot_id,
        payload=json.dumps(service.strip_pii(event), separators=(",", ":"))[:200_000],
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        row = db.scalar(
            select(BillingEvent).where(
                BillingEvent.provider == provider, BillingEvent.event_id == ev.event_id
            )
        )
        if row is None or row.processed_at is not None:
            return {"received": True, "duplicate": True}
        # A retry of an event whose processing failed earlier: run it again.

    row_id = row.id
    try:
        outcome = service.handle_event(db, settings, ev)
        row = db.get(BillingEvent, row_id)
        row.processed_at = utcnow()
        row.error = outcome.note
        db.commit()
    except Exception as e:  # noqa: BLE001 - stored on the event; the provider retries
        db.rollback()
        msg = scrub(f"{type(e).__name__}: {e}", _secrets(settings))[:500]
        log.error("billing webhook %s %s failed: %s", provider, ev.event_id, msg)
        row = db.get(BillingEvent, row_id)
        if row is not None:
            row.error = msg
            db.commit()
        background.add_task(
            operator.ping, settings, f"mebot: billing webhook failed ({provider} {ev.type})"
        )
        return JSONResponse(
            error_body(500, "WEBHOOK_FAILED", "Processing failed; retry later."),
            status_code=500,
            background=background,
        )
    for text in outcome.pings:
        background.add_task(operator.ping, settings, text)
    return {"received": True}
