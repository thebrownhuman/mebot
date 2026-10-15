"""Rate limits and usage caps for public endpoints.

``Limiter`` is the interface the routes use; ``ChatLimiter`` is the single-process
implementation (memory for short windows, DB counters for daily/session counts).
"""

from typing import Protocol

from sqlalchemy.orm import Session

from mebot.models import BotLimits


class Limiter(Protocol):
    def check_and_consume(
        self, db: Session, bot_id: str, limits: BotLimits, ip: str | None, session_id: str
    ) -> None:
        """Count one chat message, or raise ``LimitExceeded``."""

    def record_tokens(
        self, db: Session, bot_id: str, ip: str | None, tokens: int, *, estimated: bool
    ) -> None: ...

    def session_start_wait(self, limits: BotLimits, ip: str | None) -> int | None: ...
