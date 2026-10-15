import math

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from mebot.db import get_db
from mebot.deps import client_ip, get_current_bot, require_setup_done
from mebot.errors import ApiError
from mebot.limits.service import LimitExceeded
from mebot.llm import service as llm
from mebot.llm.base import LLMError
from mebot.marker import MarkerFilter
from mebot.models import Bot
from mebot.profile.data import load_profile
from mebot.prompt import build_system_prompt, render_profile
from mebot.repos import limits as limits_repo
from mebot.repos import llm_configs, logs, sessions

router = APIRouter(prefix="/api")

# Shown to visitors whenever the owner's provider fails; details go to access_log only.
UNAVAILABLE = "Sorry, the assistant is unavailable right now. Please try again later."
PAUSED = "The assistant is paused right now. Please try again later."
# Body-size guard only; the owner's max_message_chars (100-4000) is checked in the route.
HARD_MAX_CHARS = 20_000


class ChatReq(BaseModel):
    session_id: str = Field(max_length=64)
    message: str = Field(max_length=HARD_MAX_CHARS)

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
    ip = client_ip(request)
    # Order matters (spec): paused -> configured -> length -> rate limits -> LLM.
    limits = limits_repo.get_or_create(db, bot_id)
    if limits.paused:
        raise ApiError(503, "BOT_PAUSED", limits.paused_message or PAUSED)
    status, _, cfg = llm.load(db, bot_id, request.app.state.secret_key)
    if cfg is None:
        raise ApiError(503, "LLM_NOT_CONFIGURED", UNAVAILABLE)
    if len(req.message) > limits.max_message_chars:
        raise ApiError(
            422,
            "MESSAGE_TOO_LONG",
            f"Please keep messages under {limits.max_message_chars} characters.",
            details=[{"field": "message", "message": f"max {limits.max_message_chars} characters"}],
        )
    if sessions.get(db, bot_id, req.session_id) is None:
        raise HTTPException(404, "Unknown session")
    limiter = request.app.state.chat_limiter
    try:
        limiter.check_and_consume(db, bot_id, limits, ip, req.session_id)
    except LimitExceeded as e:
        db.rollback()
        if limiter.should_log(e.scope, limiter.ip_key(ip)):
            logs.add(db, bot_id, req.session_id, "RATE_LIMITED", detail=e.scope)
            db.commit()
        raise e.api_error() from None

    # Only the last N stored turns go to the LLM: cheaper, and long-conversation
    # jailbreaks lose their run-up. The system prompt is always sent.
    stored = sessions.messages(db, bot_id, req.session_id)
    history = [{"role": m.role, "content": m.content} for m in stored[-limits.history_turns :]]
    profile = render_profile(load_profile(db, bot_id))
    sessions.add_message(db, bot_id, req.session_id, "user", req.message)
    logs.add(db, bot_id, req.session_id, "question", detail=req.message[:200], ip=ip)
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
            usage = getattr(client, "usage", None)
            if usage is not None:
                tokens, estimated = usage.total, False
            else:
                prompt_chars = sum(len(m["content"]) for m in messages)
                tokens = math.ceil(prompt_chars / 4) + math.ceil(len("".join(acc)) / 4)
                estimated = True
            # Fresh DB session: the request-scoped one may be closed while we stream.
            with session_factory() as wdb:
                if full:
                    sessions.add_message(
                        wdb, bot_id, req.session_id, "assistant", full, unanswered=marker.found
                    )
                limiter.record_tokens(wdb, bot_id, ip, tokens, estimated=estimated)
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
