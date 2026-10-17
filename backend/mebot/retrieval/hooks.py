"""Schedule a reindex after the profile changes (save, import apply, learned-fact approve).

A FastAPI dependency so routes stay one line: ``reindex(bot.id)`` queues a background task
that runs after the response is sent, so the owner never waits on it.
"""

from fastapi import BackgroundTasks, Request

from mebot.retrieval import index

# Profile sections whose items become chunks (identity, links and avoid-topics are
# always in the prompt instead).
CHUNKED = frozenset(
    {"experiences", "educations", "skills", "projects", "interests", "faqs", "notes", "learned"}
)


class Reindexer:
    def __init__(self, request: Request, background: BackgroundTasks):
        self._request = request
        self._background = background

    def __call__(self, bot_id: str, section: str | None = None, *, force: bool = False) -> None:
        if section is not None and section not in CHUNKED:
            return
        state = self._request.app.state
        self._background.add_task(
            index.reindex,
            state.session_factory,
            bot_id,
            state.secret_key,
            state.chat_limiter,
            threshold=state.settings.retrieval_threshold_tokens,
            force=force,
        )


def get_reindexer(request: Request, background: BackgroundTasks) -> Reindexer:
    return Reindexer(request, background)
