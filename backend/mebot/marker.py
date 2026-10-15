"""The [[UNANSWERED]] marker the model appends when the profile can't answer a question.

``MarkerFilter`` removes it from a token stream before anything reaches the visitor,
even when the marker is split across chunks: it holds back only the trailing text
that could still turn into a marker, and releases it as soon as it can't.
"""

import re

UNANSWERED_MARKER = "[[UNANSWERED]]"
# Tolerates case and inner whitespace: "[[ unanswered ]]".
MARKER_RE = re.compile(r"\[\[\s*unanswered\s*\]\]", re.IGNORECASE)
_WORD = "unanswered"


def neutralise(text: str) -> str:
    """Defuse markers inside owner data so the profile can't trigger false positives."""
    return MARKER_RE.sub("[UNANSWERED]", text)


def _could_become_marker(s: str) -> bool:
    """True if s (starting with '[') is an incomplete prefix of a marker."""
    i, n = 0, len(s)
    for _ in range(2):
        if i == n:
            return True
        if s[i] != "[":
            return False
        i += 1
    while i < n and s[i].isspace():
        i += 1
    for ch in _WORD:
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
        self.found = False

    def _strip(self) -> None:
        cleaned, count = MARKER_RE.subn("", self._buf)
        if count:
            self.found = True
            self._buf = cleaned

    def feed(self, chunk: str) -> str:
        """Add a chunk; return the text that is now safe to show."""
        self._buf += chunk
        self._strip()
        hold = len(self._buf)
        # Earliest '[' whose tail could still complete into a marker.
        pos = self._buf.find("[")
        while pos != -1:
            if _could_become_marker(self._buf[pos:]):
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
