"""The assistant persona: always third person, about the owner.

Pronouns come from ``profile_identity.pronouns``; ``they/them`` (the default) means the
prompt and FACTS use the owner's name or "they" instead of guessing a gender.
"""

from dataclasses import dataclass

PRONOUN_CHOICES = ("he/him", "she/her", "they/them")
DEFAULT_PRONOUNS = "they/them"
FALLBACK_NAME = "the candidate"
DEFAULT_GREETING = (
    "Hi! I'm {first_name}'s assistant. Ask me anything about {pronoun_obj} work, "
    "experience or projects."
)
MAX_GREETING = 300


@dataclass(frozen=True)
class Pronouns:
    subject: str
    object: str
    possessive: str  # determiner: "his work", "their work"


_FORMS = {
    "he/him": Pronouns("he", "him", "his"),
    "she/her": Pronouns("she", "her", "her"),
    "they/them": Pronouns("they", "them", "their"),
}


def pronouns_for(value: str | None) -> Pronouns:
    return _FORMS.get(value or DEFAULT_PRONOUNS, _FORMS[DEFAULT_PRONOUNS])


def first_name(full_name: str | None) -> str:
    parts = (full_name or "").split()
    return parts[0] if parts else ""


def display_name(identity: dict, fallback: str | None = None) -> str:
    """The owner's first name as the bot should use it; "the candidate" when unknown."""
    return first_name(identity.get("full_name")) or first_name(fallback) or FALLBACK_NAME


def render_greeting(
    identity: dict, bot_name: str | None = None, template: str | None = None
) -> str:
    """The first bubble the recruiter sees. Not an LLM call.

    Placeholders: {first_name}, {name}, {pronoun_subj}, {pronoun_obj} (the possessive
    "his/her/their", so the default reads "about their work")."""
    tpl = (template if template is not None else identity.get("assistant_greeting")) or ""
    tpl = tpl.strip() or DEFAULT_GREETING
    pron = pronouns_for(identity.get("pronouns"))
    first = first_name(identity.get("full_name")) or first_name(bot_name) or "the owner"
    values = {
        "first_name": first,
        "name": (identity.get("full_name") or "").strip() or (bot_name or first),
        "pronoun_subj": pron.subject,
        "pronoun_obj": pron.possessive,
    }
    try:
        return tpl.format_map(_Safe(values))
    except (ValueError, IndexError):  # stray braces in an owner-written greeting
        return DEFAULT_GREETING.format_map(values)


class _Safe(dict):
    """Unknown {placeholders} stay as typed instead of raising."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"
