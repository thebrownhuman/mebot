"""In-memory abuse limits. IPs are used only as transient dictionary keys: never stored."""

import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import date
from threading import Lock


class SlidingWindow:
    """At most ``limit`` hits per ``window`` seconds per key; ``hit`` returns the seconds
    to wait when refused, else None."""

    def __init__(self, limit: int, window: int, clock: Callable[[], float] = time.monotonic):
        self.limit, self.window, self.clock = limit, window, clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def hit(self, key: str) -> int | None:
        now = self.clock()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] >= self.window:
                q.popleft()
            if len(q) >= self.limit:
                return max(1, int(self.window - (now - q[0]) + 0.999))
            q.append(now)
            if len(self._hits) > 50_000:  # bound memory under a flood of distinct IPs
                for k in [k for k, v in self._hits.items() if not v][:10_000]:
                    del self._hits[k]
            return None


class DailyCounter:
    """Counts events per key per UTC day, e.g. new install ids created by one IP."""

    def __init__(self, limit: int):
        self.limit = limit
        self._day: date | None = None
        self._counts: dict[str, int] = defaultdict(int)
        self._lock = Lock()

    def allow(self, key: str, today: date) -> bool:
        with self._lock:
            if self._day != today:
                self._day, self._counts = today, defaultdict(int)
            return self._counts[key] < self.limit

    def add(self, key: str, today: date) -> None:
        with self._lock:
            if self._day != today:
                self._day, self._counts = today, defaultdict(int)
            self._counts[key] += 1
