"""Public-chat limits: one entry point, ``check_and_consume``, in the spec's order.

per-IP minute (memory) -> per-IP day -> per-session -> bot daily messages (DB, atomic)
-> bot daily tokens. Pause / setup / message length are checked by the route first.
"""

import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from threading import Lock

from sqlalchemy.orm import Session

from mebot.limits import counters
from mebot.limits.memory import SlidingWindowLimiter
from mebot.models import BotLimits

FRIENDLY = {
    "ip_minute": "You're sending messages quickly — please wait a minute.",
    "ip_day": "You've reached today's message limit. Please come back tomorrow.",
    "session": "This conversation has reached its message limit. Please start a new chat.",
    "bot_day": "The assistant has reached its daily limit. Please come back tomorrow.",
    "bot_tokens": "The assistant has reached its daily limit. Please come back tomorrow.",
    "session_start": "Too many new chats from your network. Please try again later.",
}
_CODES = {"bot_day": "DAILY_CAP_REACHED", "bot_tokens": "DAILY_CAP_REACHED"}
_LOG_EVERY = 60.0


class LimitExceeded(Exception):
    def __init__(self, scope: str, retry_after: int | None):
        super().__init__(scope)
        self.scope = scope
        self.retry_after = retry_after
        self.code = _CODES.get(scope, "RATE_LIMITED")
        self.message = FRIENDLY[scope]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ChatLimiter:
    """Single-process implementation; a Redis-backed one can replace the memory windows."""

    def __init__(
        self,
        secret_key: str,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], datetime] = _utcnow,
    ):
        self.secret_key = secret_key
        self.clock = clock
        self.wall = wall
        self._minute = SlidingWindowLimiter(10, 60, lambda: self.clock())
        self._sessions = SlidingWindowLimiter(10, 3600, lambda: self.clock())
        self._logged: dict[tuple[str, str], float] = {}
        self._lock = Lock()

    def today(self) -> date:
        return self.wall().astimezone(UTC).date()

    def seconds_to_midnight(self) -> int:
        now = self.wall().astimezone(UTC)
        midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), UTC)
        return max(1, int((midnight - now).total_seconds() + 0.999))

    def ip_key(self, ip: str | None) -> str:
        return counters.ip_hash(self.secret_key, ip)

    def check_and_consume(
        self, db: Session, bot_id: str, limits: BotLimits, ip: str | None, session_id: str
    ) -> None:
        """Count one chat message or raise LimitExceeded. The caller commits."""
        ipk = self.ip_key(ip)
        wait = self._minute.hit(f"{bot_id}:{ipk}", limits.per_ip_per_minute)
        if wait is not None:
            raise LimitExceeded("ip_minute", wait)
        day = self.today()
        failed = counters.consume(
            db,
            bot_id,
            [
                ("ip_day", ipk, limits.per_ip_per_day),
                ("session", session_id, limits.per_session_messages),
                ("bot_day", "*", limits.daily_message_cap),
            ],
            day,
        )
        if failed is not None:
            raise LimitExceeded(failed, None if failed == "session" else self.seconds_to_midnight())
        if limits.daily_token_cap is not None:
            row = counters.get(db, bot_id, "bot_day", "*", day)
            if row is not None and row.tokens >= limits.daily_token_cap:
                counters.release(
                    db, bot_id, [("ip_day", ipk), ("session", session_id), ("bot_day", "*")], day
                )
                raise LimitExceeded("bot_tokens", self.seconds_to_midnight())

    def record_tokens(
        self, db: Session, bot_id: str, ip: str | None, tokens: int, *, estimated: bool
    ) -> None:
        counters.add_tokens(
            db,
            bot_id,
            [("bot_day", "*"), ("ip_day", self.ip_key(ip))],
            self.today(),
            tokens,
            estimated=estimated,
            now=self.wall(),
        )

    def session_start_wait(self, limits: BotLimits, ip: str | None) -> int | None:
        return self._sessions.hit(self.ip_key(ip), limits.sessions_per_ip_per_hour)

    def should_log(self, scope: str, key: str) -> bool:
        """RATE_LIMITED is logged at most once per (scope, key) per minute."""
        now = self.clock()
        with self._lock:
            last = self._logged.get((scope, key))
            if last is not None and now - last < _LOG_EVERY:
                return False
            if len(self._logged) > 10_000:
                self._logged = {k: v for k, v in self._logged.items() if now - v < _LOG_EVERY}
            self._logged[(scope, key)] = now
            return True
