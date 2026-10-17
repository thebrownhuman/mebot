"""Owner's conversations: filter, search, read, export, delete."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from mebot import conversations as conv
from mebot import retention
from mebot.analytics import cache
from mebot.db import get_db
from mebot.deps import csrf_on_mutation, get_current_admin, get_current_bot, require_setup_done
from mebot.errors import ApiError
from mebot.models import Bot
from mebot.repos import logs

router = APIRouter(
    prefix="/api/admin",
    dependencies=[
        Depends(require_setup_done),
        Depends(get_current_admin),
        Depends(csrf_on_mutation),
    ],
)


class FilterParams:
    """The query string shared by the list and the export."""

    def __init__(
        self,
        range: str | None = Query(None, description="7d | 30d | 90d"),
        from_: str | None = Query(None, alias="from", max_length=10),
        to: str | None = Query(None, max_length=10),
        q: str | None = Query(None, max_length=200),
        has: str | None = Query(None, max_length=100),
        origin: str | None = Query(None, max_length=300),
        bot: Bot = Depends(get_current_bot),
    ):
        self.filters = conv.parse_filters(
            bot, range=range, date_from=from_, date_to=to, q=q, has=has, origin=origin
        )


@router.get("/conversations")
def list_conversations(
    p: FilterParams = Depends(),
    cursor: str | None = Query(None, max_length=200),
    limit: int = Query(25, ge=1, le=100),
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    items, nxt = conv.list_page(db, bot.id, p.filters, cursor, limit)
    return {"items": items, "next_cursor": nxt}


@router.get("/conversations/export")
def export_conversations(
    request: Request,
    p: FilterParams = Depends(),
    format: Literal["csv", "json"] = Query("csv"),
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    total = conv.export_count(db, bot.id, p.filters)
    if total > conv.MAX_EXPORT_MESSAGES:
        raise ApiError(
            422,
            "EXPORT_TOO_LARGE",
            f"This export has {total:,} messages; the limit is {conv.MAX_EXPORT_MESSAGES:,}. "
            "Choose a shorter date range or add a filter.",
        )
    bot_id, filters = bot.id, p.filters
    factory = request.app.state.session_factory

    def body():
        # Its own session: the request's is closed by the time the stream is read.
        with factory() as sdb:
            rows = conv.export_rows(sdb, bot_id, filters)
            yield from (conv.csv_stream if format == "csv" else conv.json_stream)(rows)

    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    media = "text/csv; charset=utf-8" if format == "csv" else "application/json"
    return StreamingResponse(
        body(),
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="mebot-conversations-{stamp}.{format}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/conversations/{sid}")
def get_conversation(sid: str, db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)):
    found = conv.detail(db, bot.id, sid)
    if found is None:
        raise ApiError(404, "NOT_FOUND", "This conversation no longer exists.")
    return found


@router.delete("/conversations/{sid}", status_code=204)
def delete_conversation(
    sid: str, db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)
):
    """Owner-initiated removal of a visitor's personal data: a hard delete."""
    if retention.delete_sessions(db, bot.id, [sid])["sessions"] == 0:
        raise ApiError(404, "NOT_FOUND", "This conversation no longer exists.")
    logs.add(db, bot.id, None, "CONVERSATION_DELETED")
    db.commit()
    cache.invalidate(bot.id)
    return Response(status_code=204)
