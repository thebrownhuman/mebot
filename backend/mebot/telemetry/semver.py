"""Just enough semver for update checks and advisory matching.

Versions compare by their ``major.minor.patch`` base. A dev build (``0.9.0-dev``) is never
"behind" the release it was cut from, so it doesn't show an update banner for it.
"""

import operator
import re

_VERSION = re.compile(r"^v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})(?:[-+][0-9A-Za-z.+-]{1,30})?$")
_COMPARATOR = re.compile(r"^(<=|>=|==|=|<|>)\s*(\S+)$")
_OPS = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
    "=": operator.eq,
}

Triple = tuple[int, int, int]


def parse(version: str | None) -> Triple | None:
    m = _VERSION.match((version or "").strip())
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def valid(version: str | None) -> bool:
    return parse(version) is not None


def major(version: str) -> int | None:
    t = parse(version)
    return t[0] if t else None


def update_available(latest: str | None, current: str) -> bool:
    a, b = parse(latest), parse(current)
    return a is not None and b is not None and a > b


def affected(spec: str, current: str) -> bool:
    """Whether ``current`` matches an advisory range like ``<0.10.1`` or ``>=0.9.0,<0.10.1``.
    An unparseable range matches nothing."""
    cur = parse(current)
    parts = [p.strip() for p in (spec or "").split(",") if p.strip()]
    if cur is None or not parts:
        return False
    for part in parts:
        m = _COMPARATOR.match(part)
        bound = parse(m[2]) if m else None
        if m is None or bound is None or not _OPS[m[1]](cur, bound):
            return False
    return True
