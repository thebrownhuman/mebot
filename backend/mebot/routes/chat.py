from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from mebot.db import get_db
from mebot.deps import client_ip, get_current_bot, require_setup_done
from mebot.errors import ApiError
from mebot.llm import service as llm
from mebot.llm.base import LLMError
from mebot.marker import MarkerFilter
from mebot.models import Bot
from mebot.profile.data import load_profile
from mebot.prompt import build_system_prompt, render_profile
from mebot.repos import llm_configs, logs, sessions

router = APIRouter(prefix="/api")

# Shown to visitors whenever the owner's provider fails; details go to access_log only.
UNAVAILABLE = "Sorry, the assistant is unavailable right now. Please try again later."


class ChatReq(BaseModel):
    session_id: str
    message: str

    @field_validator("message")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message must not be empty")
        return v


def _error_detail(provider: str, exc: Exception) -> str:
    # Never the provider's message or body: it may echo request data.
    if isinstance(exc, LLMError):
        return f"provider={provider} status={exc.status} kind={exc.kind}"
    return f"provider={provider} status=None kind=unexpected:{type(exc).__name__}"


@router.post("/chat", dependencies=[Depends(require_setup_done)])
async def chat(
    req: ChatReq,
    request: Request,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    bot_id = bot.id
    if sessions.get(db, bot_id, req.session_id) is None:
        raise HTTPException(404, "Unknown session")
    status, _, cfg = llm.load(db, bot_id, request.app.state.secret_key)
    if cfg is None:
        raise ApiError(503, "LLM_NOT_CONFIGURED", UNAVAILABLE)

    history = [
        {"role": m.role, "content": m.content}
        for m in sessions.messages(db, bot_id, req.session_id)
    ]
    profile = render_profile(load_profile(db, bot_id))
    sessions.add_message(db, bot_id, req.session_id, "user", req.message)
    logs.add(
        db, bot_id, req.session_id, "question", detail=req.message[:200], ip=client_ip(request)
    )
    db.commit()

    messages = [
        {"role": "system", "content": build_system_prompt(profile)},
        *history,
        {"role": "user", "content": req.message},
    ]
    client = cfg.client()
    session_factory = request.app.state.session_factory

    async def gen():
        acc: list[str] = []
        error: Exception | None = None
        # Strips the model's [[UNANSWERED]] marker, even when split across chunks.
        marker = MarkerFilter()
        try:
            async for chunk in client.stream_chat(
                messages, model=cfg.model, temperature=cfg.temperature, max_tokens=cfg.max_tokens
            ):
                shown = marker.feed(chunk)
                if shown:
                    acc.append(shown)
                    yield shown
            tail = marker.finish()
            if tail:
                acc.append(tail)
                yield tail
        except Exception as e:  # noqa: BLE001 - visitors get a fixed message
            error = e
            tail = marker.finish()
            acc.append(tail)
            yield tail + ("\n\n" if "".join(acc) else "") + UNAVAILABLE
        finally:
            full = "".join(acc).strip()
            # Fresh DB session: the request-scoped one may be closed while we stream.
            with session_factory() as wdb:
                if full:
                    sessions.add_message(
                        wdb, bot_id, req.session_id, "assistant", full, unanswered=marker.found
                    )
                if marker.found:
                    logs.add(wdb, bot_id, req.session_id, "UNANSWERED", detail=req.message[:500])
                if getattr(client, "leaked_thinking", False):
                    logs.add(wdb, bot_id, req.session_id, "WARN_thinking_leak")
                if error is not None:
                    logs.add(
                        wdb,
                        bot_id,
                        req.session_id,
                        "LLM_ERROR",
                        detail=_error_detail(cfg.provider, error),
                    )
                    row = llm_configs.get(wdb, bot_id)
                    if row is not None:
                        llm_configs.record_test(wdb, row, ok=False)
                wdb.commit()

    return StreamingResponse(gen(), media_type="text/plain")
