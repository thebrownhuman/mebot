"""In-memory overview cache: 60 s per (bot, range); dropped when the timezone changes."""

import time
from collections.abc import Callable
from threading import Lock

TTL = 60.0
clock: Callable[[], float] = time.monotonic  # tests replace this

_store: dict[tuple[str, str, str], tuple[float, dict]] = {}
_lock = Lock()


def get(bot_id: str, range_key: str, zone: str) -> dict | None:
    with _lock:
        hit = _store.get((bot_id, range_key, zone))
        if hit and clock() - hit[0] < TTL:
            return hit[1]
    return None


def put(bot_id: str, range_key: str, zone: str, value: dict) -> None:
    with _lock:
        _store[(bot_id, range_key, zone)] = (clock(), value)


def invalidate(bot_id: str) -> None:
    with _lock:
        for key in [k for k in _store if k[0] == bot_id]:
            del _store[key]


def clear() -> None:
    with _lock:
        _store.clear()
