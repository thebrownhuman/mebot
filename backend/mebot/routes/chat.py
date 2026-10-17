import json
import math

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from mebot import channels, guard, persona
from mebot.db import get_db
from mebot.deps import client_ip, get_current_bot, require_setup_done
from mebot.errors import ApiError
from mebot.guard import personal
from mebot.guard.channels import ChannelGuard
from mebot.hosted import caps
from mebot.limits import counters
from mebot.limits.service import LimitExceeded
from mebot.llm import service as llm
from mebot.llm.base import LLMError
from mebot.marker import MarkerFilter
from mebot.models import Bot
from mebot.profile.data import load_profile
from mebot.prompt import build_system_prompt
from mebot.repos import limits as limits_repo
from mebot.repos import llm_configs, logs, open_questions, sessions
from mebot.repos import retrieval as retrieval_repo
from mebot.retrieval import service as retrieval
from mebot.telegram import events

router = APIRouter(prefix="/api")

# Shown to visitors whenever the owner's provider fails; details go to access_log only.
UNAVAILABLE = "Sorry, the assistant is unavailable right now. Please try again later."
PAUSED = "The assistant is paused right now. Please try again later."
# Starts the stream's one control frame: \x1e{"type":"replace","content":...}. Model output
# never contains it (stripped), so the UI can trust whatever follows it.
FRAME_SEP = "\x1e"
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


def replace_frame(content: str) -> str:
    return FRAME_SEP + json.dumps({"type": "replace", "content": content})


def _error_detail(provider: str, exc: Exception) -> str:
    # Never the provider's message or body: it may echo request data.
    if isinstance(exc, LLMError):
        return f"provider={provider} status={exc.status} kind={exc.kind}"
    return f"provider={provider} status=None kind=unexpected:{type(exc).__name__}"


class _QueryEmbedder:
    """Embeds the visitor's query with the owner's provider; counts the tokens it spent."""

    def __init__(self, client):
        self.client = client
        self.tokens = 0

    async def __call__(self, texts: list[str], model: str) -> list[list[float]]:
        vectors = await self.client.embed(texts, model=model)
        reported = getattr(self.client, "embed_tokens", None)
        self.tokens += reported or sum(math.ceil(len(t) / 4) for t in texts)
        return vectors


def _query_embedder(db: Session, bot_id: str, cfg) -> "_QueryEmbedder | None":
    row = retrieval_repo.get_settings(db, bot_id)
    if row is None or not (row.embeddings_enabled and row.embedding_model):
        return None
    return _QueryEmbedder(cfg.client())


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
    limits = caps.clamp(limits_repo.get_or_create(db, bot_id), request.app.state.settings)
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
    chat_session = sessions.get(db, bot_id, req.session_id)
    if chat_session is None:
        raise HTTPException(404, "Unknown session")
    visitor = chat_session.recruiter_name
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
    history = [
        {
            "role": m.role,
            "content": guard.wrap_visitor(m.content) if m.role == "user" else m.content,
        }
        for m in stored[-limits.history_turns :]
    ]
    # Layer (a) of the professional filter: a hint, never a verdict (mebot.guard.personal).
    hint = personal.classify(req.message)
    profile_data = load_profile(db, bot_id)
    # Large profiles: only the relevant parts (+ always-on facts and an outline) are sent.
    # The query is this message plus the previous one, for follow-ups.
    previous = next((m.content for m in reversed(stored) if m.role == "user"), None)
    embedder = _query_embedder(db, bot_id, cfg)
    cfg_settings = request.app.state.settings
    knowledge = await retrieval.knowledge_for(
        db,
        bot_id,
        profile_data,
        [req.message, *([previous] if previous else [])],
        threshold=cfg_settings.retrieval_threshold_tokens,
        budget=cfg_settings.retrieval_budget_tokens,
        embedder=embedder,
    )
    owner = persona.display_name(profile_data.identity, bot.name)
    pronouns = profile_data.identity.get("pronouns") or persona.DEFAULT_PRONOUNS
    contact_channels = channels.from_items(profile_data.items("links"))
    legacy_contact = [  # pre-0010 identity columns: unused, but never to be revealed
        profile_data.identity.get(k) or "" for k in ("email_public", "phone_public")
    ]
    sessions.add_message(db, bot_id, req.session_id, "user", req.message)
    logs.add(
        db,
        bot_id,
        req.session_id,
        "question",
        detail=req.message[:200],
        ip_hash=counters.stored_ip_hash(request.app.state.secret_key, ip),
    )
    # Telegram notifications are queued in the same transaction as the event.
    # Personal-looking questions are never forwarded to the owner.
    if hint is None:
        events.question(db, bot_id, req.session_id, visitor, req.message)
    bot_day = counters.get(db, bot_id, "bot_day", "*", limiter.today())
    if bot_day is not None:
        events.cap_warning(db, bot_id, bot_day.messages, limits.daily_message_cap, limiter.today())
    db.commit()

    suspicious = guard.looks_like_injection(req.message)
    if suspicious:  # logged, not blocked: innocent questions trip this too
        logs.add(db, bot_id, req.session_id, "INJECTION_SUSPECTED", detail=req.message[:200])
        db.commit()
    canary = guard.canary_for(request.app.state.secret_key, bot_id)
    system = build_system_prompt(
        knowledge.text,
        excerpted=knowledge.retrieval,
        canary=canary,
        reminder=suspicious,
        name=owner,
        pronouns=pronouns,
        personal_hint=hint,
    )
    messages = [
        {"role": "system", "content": system},
        *history,
        {"role": "user", "content": guard.wrap_visitor(req.message)},
    ]
    client = cfg.client()
    session_factory = request.app.state.session_factory
    public_url = request.app.state.settings.public_url

    async def gen():
        acc: list[str] = []
        error: Exception | None = None
        # Strips the model's [[UNANSWERED]] / [[PERSONAL]] markers, even when split across chunks.
        marker = MarkerFilter()
        # Cuts the reply if the canary or a verbatim slice of the rules shows up.
        leak = guard.LeakGuard(canary, system)
        # Replaces non-shared contact values (and any phone-shaped string) with [hidden].
        chan = ChannelGuard(contact_channels, legacy_contact)
        produced = 0  # model output chars, for the token estimate
        try:
            async for chunk in client.stream_chat(
                messages, model=cfg.model, temperature=cfg.temperature, max_tokens=cfg.max_tokens
            ):
                produced += len(chunk)
                chunk = chunk.replace(FRAME_SEP, "")
                shown = leak.feed(chan.feed(marker.feed(chunk)))
                if leak.tripped:
                    break
                if shown:
                    acc.append(shown)
                    yield shown
            if not leak.tripped:
                tail = leak.feed(chan.feed(marker.finish()) + chan.finish())
                tail += "" if leak.tripped else leak.finish()
                if tail:
                    acc.append(tail)
                    yield tail
            if leak.tripped:
                yield ("\n\n" if "".join(acc) else "") + guard.SAFE_REPLY
                # The visible bubble still holds the text streamed before the cut.
                yield replace_frame(guard.SAFE_REPLY)
            elif chan.redactions:
                yield replace_frame("".join(acc).strip())
        except Exception as e:  # noqa: BLE001 - visitors get a fixed message
            error = e
            tail = (
                ""
                if leak.tripped
                else leak.feed(chan.feed(marker.finish()) + chan.finish()) + leak.finish()
            )
            if not leak.tripped:
                acc.append(tail)
                yield tail + ("\n\n" if "".join(acc) else "") + UNAVAILABLE
        finally:
            full = guard.SAFE_REPLY if leak.tripped else "".join(acc).strip()
            usage = getattr(client, "usage", None)
            if usage is not None:
                tokens, estimated = usage.total, False
            else:
                prompt_chars = sum(len(m["content"]) for m in messages)
                tokens = math.ceil(prompt_chars / 4) + math.ceil(produced / 4)
                estimated = True
            if embedder is not None:  # the paid query-embedding call, if one was made
                tokens += embedder.tokens
            # Fresh DB session: the request-scoped one may be closed while we stream.
            with session_factory() as wdb:
                # Personal topics are declined, not learned: the model said so, or the
                # keyword layer matched and the model also didn't know. Never an open
                # question, never a Telegram ping, unanswered stays false.
                declined = marker.personal or (hint is not None and marker.found)
                unanswered = marker.found and not declined
                reply = None
                if full:
                    reply = sessions.add_message(
                        wdb,
                        bot_id,
                        req.session_id,
                        "assistant",
                        full,
                        unanswered=unanswered,
                        chunk_ids=knowledge.chunk_ids if knowledge.retrieval else None,
                    )
                limiter.record_tokens(wdb, bot_id, ip, tokens, estimated=estimated)
                if knowledge.retrieval:  # prompt vs whole-profile tokens, for the savings readout
                    logs.add(
                        wdb,
                        bot_id,
                        req.session_id,
                        "RETRIEVAL",
                        detail=f"{knowledge.prompt_tokens}/{knowledge.profile_tokens}",
                    )
                if chan.redactions:  # the count only, never the value
                    logs.add(
                        wdb, bot_id, req.session_id, "CHANNEL_REDACTED", detail=str(chan.redactions)
                    )
                if leak.tripped:
                    logs.add(wdb, bot_id, req.session_id, "LEAK_BLOCKED")
                    events.leak_blocked(wdb, bot_id)
                if declined:
                    # The category only, never the question text.
                    logs.add(
                        wdb, bot_id, req.session_id, "PERSONAL_DECLINED", detail=hint or "model"
                    )
                    events.retract_question(wdb, bot_id, req.session_id)
                elif unanswered:
                    logs.add(wdb, bot_id, req.session_id, "UNANSWERED", detail=req.message[:500])
                    group, _ = open_questions.record(wdb, bot_id, req.message, req.session_id)
                    events.unanswered(
                        wdb,
                        bot_id,
                        req.session_id,
                        visitor,
                        req.message,
                        reply.id if reply else None,
                        public_url,
                        group=group,
                    )
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
