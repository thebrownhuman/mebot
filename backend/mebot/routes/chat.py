from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from mebot.config import Settings
from mebot.db import get_db
from mebot.deps import client_ip, get_current_bot, get_settings
from mebot.llm import ollama
from mebot.models import Bot
from mebot.prompt import build_system_prompt
from mebot.repos import logs, profiles, sessions

router = APIRouter(prefix="/api")


class ChatReq(BaseModel):
    session_id: str
    message: str

    @field_validator("message")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message must not be empty")
        return v


@router.post("/chat")
async def chat(
    req: ChatReq,
    request: Request,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
    settings: Settings = Depends(get_settings),
):
    bot_id = bot.id
    if sessions.get(db, bot_id, req.session_id) is None:
        raise HTTPException(404, "Unknown session")
    history = [
        {"role": m.role, "content": m.content}
        for m in sessions.messages(db, bot_id, req.session_id)
    ]

    h = await ollama.health(settings.ollama_host, settings.ollama_model)
    if not h.get("model"):
        raise HTTPException(503, h.get("message", "Ollama not ready"))

    profile = profiles.get_content(db, bot_id)
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
    payload = ollama.build_payload(h["model"], messages)
    session_factory = request.app.state.session_factory

    async def gen():
        acc: list[str] = []
        try:
            async for chunk in ollama.stream_chat(settings.ollama_host, payload):
                acc.append(chunk)
                yield chunk
        except Exception as e:  # noqa: BLE001 - shown to the user, as in the prototype
            yield f"\n[error contacting model: {e}]"
        finally:
            full = "".join(acc).strip()
            # Fresh DB session: the request-scoped one may be closed while we stream.
            with session_factory() as wdb:
                if full:
                    sessions.add_message(wdb, bot_id, req.session_id, "assistant", full)
                if payload.get("_leaked_thinking"):
                    logs.add(wdb, bot_id, req.session_id, "WARN_thinking_leak")
                wdb.commit()

    return StreamingResponse(gen(), media_type="text/plain")
