"""The [[UNANSWERED]] marker the model appends when the profile can't answer a question."""

import re

UNANSWERED_MARKER = "[[UNANSWERED]]"
# Tolerates case and inner whitespace: "[[ unanswered ]]".
MARKER_RE = re.compile(r"\[\[\s*unanswered\s*\]\]", re.IGNORECASE)


def neutralise(text: str) -> str:
    """Defuse markers inside owner data so the profile can't trigger false positives."""
    return MARKER_RE.sub("[UNANSWERED]", text)
