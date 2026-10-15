"""Login brute-force limiter. In-memory (single process); swap via the LoginLimiter protocol."""

import time
from collections import defaultdict, deque
from collections.abc import Callable
from threading import Lock
from typing import Protocol


class LoginLimiter(Protocol):
    def retry_after(self, ip: str | None, email: str) -> int | None:
        """Seconds until another attempt is allowed, or None if allowed now."""

    def record_failure(self, ip: str | None, email: str) -> None: ...


class InMemoryLoginLimiter:
    def __init__(
        self,
        max_per_ip: int = 5,
        max_per_email: int = 10,
        window_seconds: int = 15 * 60,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.max_per_ip = max_per_ip
        self.max_per_email = max_per_email
        self.window = window_seconds
        self.clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def _keys(self, ip: str | None, email: str) -> list[tuple[str, int]]:
        keys = [(f"email:{email.strip().lower()}", self.max_per_email)]
        if ip:
            keys.append((f"ip:{ip}", self.max_per_ip))
        return keys

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._hits.get(key)
        if q is None:
            return deque()
        while q and q[0] <= now - self.window:
            q.popleft()
        if not q:
            del self._hits[key]
        return q

    def retry_after(self, ip: str | None, email: str) -> int | None:
        now = self.clock()
        wait = 0.0
        with self._lock:
            for key, limit in self._keys(ip, email):
                q = self._prune(key, now)
                if len(q) >= limit:
                    # Allowed again once the oldest hit that keeps us at the limit expires.
                    wait = max(wait, q[len(q) - limit] + self.window - now)
        return max(1, int(wait + 0.999)) if wait > 0 else None

    def record_failure(self, ip: str | None, email: str) -> None:
        now = self.clock()
        with self._lock:
            for key, _ in self._keys(ip, email):
                self._prune(key, now)
                self._hits[key].append(now)


class SlidingWindowLimiter:
    """At most `limit` hits per key per window. hit() records and returns wait or None."""

    def __init__(
        self, limit: int, window_seconds: int, clock: Callable[[], float] = time.monotonic
    ):
        self.limit = limit
        self.window = window_seconds
        self.clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def hit(self, key: str) -> int | None:
        now = self.clock()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - self.window:
                q.popleft()
            if len(q) >= self.limit:
                return max(1, int(q[0] + self.window - now + 0.999))
            q.append(now)
            return None
