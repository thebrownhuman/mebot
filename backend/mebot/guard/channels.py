"""Output guard for contact channels (stream stage after the marker filter).

Everything the model says passes through ``ChannelGuard``. Values of channels the owner
did NOT share (and their variants: phone digits with/without ``+``/spaces, handles with
or without ``@``) are replaced with ``[hidden]``, and so is any phone-shaped string
(10+ digits) that is not a shared phone. It holds back a short tail so a value split
across chunks is still caught. ``redactions`` counts replacements; the value is never
logged.
"""

import re

from mebot.channels import Channel, digits, variants

HIDDEN = "[hidden]"
_PHONE = re.compile(r"\+?\d[\d\s().\-]{8,40}\d")
_TRAILING_DIGITS = re.compile(r"\[hidden\]\d+")
_MIN_DIGITS = 10
_PHONE_HOLD = 44  # the longest string _PHONE can match, plus slack


class ChannelGuard:
    def __init__(self, channels: list[Channel], extra_hidden: list[str] | None = None):
        shared = [c for c in channels if c.share]
        self._shared_phones = {digits(c.value) for c in shared if c.kind == "phone"}
        allowed: set[str] = set()
        for c in shared:
            allowed |= variants(c)
        hidden: set[str] = set()
        for c in channels:
            if not c.share:
                hidden |= variants(c)
        for v in extra_hidden or []:  # legacy identity contact columns (never shared)
            if v and v.strip():
                hidden |= variants(Channel("other", "", v.strip(), False))
                if len(digits(v)) >= _MIN_DIGITS:
                    hidden.add(digits(v))
        self._allowed = allowed
        # A value that is also shared (e.g. the same handle twice) stays visible.
        self._hidden = sorted(hidden - allowed, key=len, reverse=True)
        self._hold = max([len(h) for h in self._hidden] + [_PHONE_HOLD])
        self._pending = ""
        self.redactions = 0

    def _spans(self, text: str) -> list[tuple[int, int]]:
        low = text.lower()
        shared = [
            (m.start(), m.end()) for a in self._allowed for m in re.finditer(re.escape(a), low)
        ]
        spans: list[tuple[int, int]] = []

        def free(s: int, e: int) -> bool:  # not inside a span the owner shares
            return not any(a <= s and e <= b for a, b in shared)

        for h in self._hidden:
            for m in re.finditer(re.escape(h), low):
                if free(m.start(), m.end()):
                    spans.append((m.start(), m.end()))
        for m in _PHONE.finditer(text):
            d = digits(m.group())
            if len(d) >= _MIN_DIGITS and d not in self._shared_phones and free(*m.span()):
                spans.append(m.span())
        return spans

    def _redact(self, text: str) -> str:
        # Digits streamed right after an already-redacted number belong to it.
        text = _TRAILING_DIGITS.sub(HIDDEN, text)
        spans = sorted(self._spans(text))
        out, pos = [], 0
        for s, e in spans:
            if s < pos:  # overlaps the previous replacement: extend it
                if e > pos:
                    pos = e
                continue
            out.append(text[pos:s])
            out.append(HIDDEN)
            self.redactions += 1
            pos = e
        out.append(text[pos:])
        return "".join(out)

    def feed(self, chunk: str) -> str:
        """Add model output; return the text now safe to show."""
        self._pending = self._redact(self._pending + chunk)
        cut = len(self._pending) - self._hold
        if cut <= 0:
            return ""
        out, self._pending = self._pending[:cut], self._pending[cut:]
        return out

    def finish(self) -> str:
        out, self._pending = self._redact(self._pending), ""
        return out
