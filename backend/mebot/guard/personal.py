"""Professional filter: topics the bot never discusses, whatever the owner's profile says.

Two layers work together:

(a) ``classify`` is a cheap keyword/regex pass over the visitor's message (English and
    common Hinglish, word boundaries so "Religare" is not "religion"). It only *hints*:
    it adds a line to the prompt, keeps the message out of Telegram, and, when the model
    also says it doesn't know, stops the question becoming an open question.
(b) the prompt rule (mebot.prompt) makes the model decline, even indirect phrasings,
    and end the reply with ``[[PERSONAL]]``, which the stream filter removes.

The categories are built in and not editable in v1. Salary, notice period, work
authorisation, city and relocation stay allowed when the owner provided them.
"""

import re

# Shown in the prompt rule; keep in sync with PATTERNS.
PROMPT_TOPICS = (
    "romantic relationships or dating, marital status, sexual orientation, religion or "
    "caste, politics, health or disability, pregnancy or family planning, age or date of "
    "birth, ethnicity or race, finances unrelated to salary, or a home address beyond "
    "the city"
)


def _rx(*patterns: str) -> re.Pattern:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)


PATTERNS: dict[str, re.Pattern] = {
    "relationship": _rx(
        r"\b(girl|boy)\s?friends?\b",
        r"\b(gf|bf)\b",
        r"\bdating\b",
        r"\b(is|are)\s+(he|she|they|you)\s+(still\s+)?single\b",
        r"\bsingle\s+(hai|ho)\b",
        r"\brelationship\s+status\b",
        r"\blove\s+life\b",
        r"\bromantic\b",
        r"\bkisi\s+se\s+pyaar\b",
    ),
    "marital_status": _rx(
        r"\b(married|unmarried|marriage|divorced?|widow(er)?|wife|husband|spouse|fianc[ée]e?)\b",
        r"\b(shaadi|shadi|shaadi\s?shuda|vivah|biwi|patni|kunwara|kunwari)\b",
    ),
    "orientation": _rx(
        r"\b(gay|lesbian|bisexual|homosexual|queer|lgbtq?\+?|transgender)\b",
        r"\bsexual(ity|\s+orientation)\b",
    ),
    "religion": _rx(
        r"\b(religion|religious|hindu|muslim|christian|sikh|jewish|buddhist|jain|atheist)\b",
        r"\b(caste|jaati|jati|dharm|dharam|mazhab|brahmin|dalit)\b",
        r"\b(church|temple|mosque|gurudwara)\b",
    ),
    "politics": _rx(
        r"\bpolitic(s|al|ian)\b",
        r"\b(election|voted?|voting|bjp|aap\s+party|democrat|republican)\b",
    ),
    "health": _rx(
        r"\b(his|her|their|your)\s+health\b",
        r"\b(mental\s+health|medical\s+(condition|history|issue)s?|health\s+(issue|problem|condition)s?)\b",
        r"\b(disabilit(y|ies)|disabled|illness|disease|cancer|diabetes|diabetic|depress(ed|ion)|anxiety)\b",
        r"\b(medication|surgery|therapy|therapist)\b",
        r"\b(bimar|bimari|beemar|beemari)\b",
    ),
    "family_planning": _rx(
        r"\bpregnan(t|cy)\b",
        r"\b(has|have|having|got|any)\s+(any\s+)?(kids|children|a\s+baby|babies)\b",
        r"\b(plan(s|ning)?)\s+(to\s+have\s+)?(a\s+)?(baby|kids|children|family)\b",
        r"\bfamily\s+planning\b",
        r"\b(bachche|bachcha|baccha|bacche)\b",
    ),
    "age": _rx(
        r"\bhow\s+old\b",
        r"\b(his|her|their|your)\s+age\b",
        r"\bwhat('?s|\s+is)\s+(the\s+)?age\b",
        r"\b(date\s+of\s+birth|dob|birth\s?day|birth\s?date)\b",
        r"\b(umar|umr|kitne\s+saal\s+ka|kitne\s+saal\s+ki)\b",
    ),
    "ethnicity": _rx(
        r"\b(ethnicity|ethnic|racial)\b",
        r"\b(his|her|their|your|what)\s+race\b",
        r"\bskin\s+colou?r\b",
    ),
    "finances": _rx(
        r"\bnet\s+worth\b",
        r"\b(bank\s+(account|balance)|credit\s+score)\b",
        r"\b(his|her|their|your)\s+(loans?|debts?|savings|investments?)\b",
        r"\bhow\s+rich\b",
    ),
    "address": _rx(
        r"\b(home|street|house|residential)\s+address\b",
        r"\b(house|flat|apartment)\s+(number|no)\b",
        r"\b(pin\s?code|zip\s?code|postal\s+code)\b",
        r"\bghar\s+ka\s+pata\b",
    ),
}


def classify(text: str) -> str | None:
    """The first personal category the text matches, or None. A hint, not a verdict."""
    for category, rx in PATTERNS.items():
        if rx.search(text):
            return category
    return None
