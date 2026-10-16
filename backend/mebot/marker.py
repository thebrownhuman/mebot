"""The [[UNANSWERED]] and [[PERSONAL]] markers the model appends to a reply.

* ``[[UNANSWERED]]``: the profile can't answer a professional question.
* ``[[PERSONAL]]``: the question was about a personal topic the bot never discusses.

``MarkerFilter`` removes them from a token stream before anything reaches the visitor,
even when a marker is split across chunks: it holds back only the trailing text that
could still turn into a marker, and releases it as soon as it can't.
"""

import re

UNANSWERED_MARKER = "[[UNANSWERED]]"
PERSONAL_MARKER = "[[PERSONAL]]"
_WORDS = ("unanswered", "personal")
# Tolerates case and inner whitespace: "[[ unanswered ]]".
MARKER_RE = re.compile(r"\[\[\s*unanswered\s*\]\]", re.IGNORECASE)
PERSONAL_RE = re.compile(r"\[\[\s*personal\s*\]\]", re.IGNORECASE)
_ANY_RE = re.compile(r"\[\[\s*(unanswered|personal)\s*\]\]", re.IGNORECASE)


def neutralise(text: str) -> str:
    """Defuse markers inside owner data so the profile can't trigger false positives."""
    return _ANY_RE.sub(lambda m: f"[{m.group(1).upper()}]", text)


def _could_become_marker(s: str, word: str) -> bool:
    """True if s (starting with '[') is an incomplete prefix of a marker with this word."""
    i, n = 0, len(s)
    for _ in range(2):
        if i == n:
            return True
        if s[i] != "[":
            return False
        i += 1
    while i < n and s[i].isspace():
        i += 1
    for ch in word:
        if i == n:
            return True
        if s[i].lower() != ch:
            return False
        i += 1
    while i < n and s[i].isspace():
        i += 1
    for _ in range(2):
        if i == n:
            return True
        if s[i] != "]":
            return False
        i += 1
    return False  # complete markers were already removed


class MarkerFilter:
    def __init__(self) -> None:
        self._buf = ""
        self.found = False  # an UNANSWERED marker was seen
        self.personal = False  # a PERSONAL marker was seen

    def _strip(self) -> None:
        def seen(m: re.Match) -> str:
            if m.group(1).lower() == "unanswered":
                self.found = True
            else:
                self.personal = True
            return ""

        self._buf = _ANY_RE.sub(seen, self._buf)

    def feed(self, chunk: str) -> str:
        """Add a chunk; return the text that is now safe to show."""
        self._buf += chunk
        self._strip()
        hold = len(self._buf)
        # Earliest '[' whose tail could still complete into a marker.
        pos = self._buf.find("[")
        while pos != -1:
            tail = self._buf[pos:]
            if any(_could_become_marker(tail, w) for w in _WORDS):
                hold = pos
                break
            pos = self._buf.find("[", pos + 1)
        out, self._buf = self._buf[:hold], self._buf[hold:]
        return out

    def finish(self) -> str:
        """End of stream: release whatever was held (it never became a marker)."""
        self._strip()
        out, self._buf = self._buf, ""
        return out
