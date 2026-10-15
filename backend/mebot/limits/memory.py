"""In-memory sliding windows (single process). Restarting the server resets them.

Used for the short windows (per-minute chat, sessions per hour, setup probes, login).
Daily and per-session counts live in the DB (``mebot.limits.counters``).
"""

import time
from collections import defaultdict, deque
from collections.abc import Callable
from threading import Lock
from typing import Protocol


def _ceil_seconds(wait: float) -> int:
    return max(1, int(wait + 0.999))


class SlidingWindowLimiter:
    """At most `limit` hits per key per window. ``hit`` records and returns the wait in
    seconds, or None when allowed. ``limit`` can be overridden per call (owner-set)."""

    def __init__(
        self, limit: int, window_seconds: int, clock: Callable[[], float] = time.monotonic
    ):
        self.limit = limit
        self.window = window_seconds
        self.clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._hits[key]
        while q and q[0] <= now - self.window:
            q.popleft()
        return q

    def _wait(self, q: deque[float], limit: int, now: float) -> int | None:
        if len(q) < limit:
            return None
        # Allowed again once the oldest hit that keeps us at the limit expires.
        return _ceil_seconds(q[len(q) - limit] + self.window - now)

    def retry_after(self, key: str, limit: int | None = None) -> int | None:
        """Peek: the wait if a hit were attempted now, without recording one."""
        now = self.clock()
        with self._lock:
            wait = self._wait(self._prune(key, now), limit or self.limit, now)
            if not self._hits[key]:
                del self._hits[key]
            return wait

    def record(self, key: str) -> None:
        now = self.clock()
        with self._lock:
            self._prune(key, now).append(now)

    def hit(self, key: str, limit: int | None = None) -> int | None:
        now = self.clock()
        with self._lock:
            q = self._prune(key, now)
            wait = self._wait(q, limit or self.limit, now)
            if wait is None:
                q.append(now)
            return wait


class LoginLimiterProtocol(Protocol):
    def retry_after(self, ip: str | None, email: str) -> int | None:
        """Seconds until another attempt is allowed, or None if allowed now."""

    def record_failure(self, ip: str | None, email: str) -> None: ...


class LoginLimiter:
    """Failed-login limiter: per IP and per email, built on the same sliding window."""

    def __init__(
        self,
        max_per_ip: int = 5,
        max_per_email: int = 10,
        window_seconds: int = 15 * 60,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.max_per_ip = max_per_ip
        self.max_per_email = max_per_email
        self._window = SlidingWindowLimiter(max_per_email, window_seconds, clock)

    def _keys(self, ip: str | None, email: str) -> list[tuple[str, int]]:
        keys = [(f"email:{email.strip().lower()}", self.max_per_email)]
        if ip:
            keys.append((f"ip:{ip}", self.max_per_ip))
        return keys

    def retry_after(self, ip: str | None, email: str) -> int | None:
        waits = [self._window.retry_after(k, lim) for k, lim in self._keys(ip, email)]
        return max((w for w in waits if w is not None), default=None)

    def record_failure(self, ip: str | None, email: str) -> None:
        for key, _ in self._keys(ip, email):
            self._window.record(key)
