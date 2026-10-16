"""Contact channels: validation per kind, public display/href, and redaction variants.

A channel is a row of ``profile_links``: ``kind`` + ``value`` + ``label`` + ``share``.
``value`` is stored canonical (see ``normalize``) so display, href and the output guard
all derive from one string.
"""

import re
from dataclasses import dataclass

KINDS = (
    "portfolio",
    "website",
    "email",
    "linkedin",
    "github",
    "instagram",
    "whatsapp",
    "telegram",
    "x",
    "phone",
    "other",
)
MAX_CHANNELS = 30
URL_KINDS = ("portfolio", "website", "linkedin", "other")
# kind -> (canonical profile URL prefix, hosts accepted when a URL is pasted)
HANDLE_KINDS = {
    "instagram": ("https://instagram.com/", ("instagram.com", "www.instagram.com")),
    "x": ("https://x.com/", ("x.com", "www.x.com", "twitter.com", "www.twitter.com")),
    "telegram": ("https://t.me/", ("t.me", "telegram.me")),
    "github": ("https://github.com/", ("github.com", "www.github.com")),
}
LABELS = {
    "portfolio": "Portfolio",
    "website": "Website",
    "email": "Email",
    "linkedin": "LinkedIn",
    "github": "GitHub",
    "instagram": "Instagram",
    "whatsapp": "WhatsApp",
    "telegram": "Telegram",
    "x": "X",
    "phone": "Phone",
    "other": "Link",
}

WHATSAPP_NUMBER_MSG = (
    "This looks like a phone number — add it as a Phone channel instead (not shared by default)."
)
_URL_RE = re.compile(r"^https?://([^/\s?#]+)([^\s]*)$", re.IGNORECASE)
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)+$")
_HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{3,64}$")
_PHONE_RE = re.compile(r"^\+?[\d\s().\-]{7,24}$")
_WA_RE = re.compile(r"^(?:https?://)?(?:www\.)?wa\.me/(.+)$", re.IGNORECASE)


class ChannelError(ValueError):
    """Value is not valid for its kind; the message is shown to the owner."""


def digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def infer_kind(url: str) -> str:
    """Kind for an old profile link, by domain (migration 0010 does the same)."""
    m = _URL_RE.match(url.strip())
    host = (m.group(1) if m else "").lower().removeprefix("www.")
    for kind, domain in (
        ("linkedin", "linkedin.com"),
        ("github", "github.com"),
        ("instagram", "instagram.com"),
    ):
        if host == domain or host.endswith("." + domain):
            return kind
    return "website"


def _http_url(v: str) -> str:
    if not _URL_RE.match(v):
        raise ChannelError("must be an http(s) URL")
    return v


def _handle_from(kind: str, v: str) -> str:
    prefix, hosts = HANDLE_KINDS[kind]
    m = _URL_RE.match(v)
    if m:
        if m.group(1).lower() not in hosts:
            raise ChannelError(f"must be a {LABELS[kind]} handle or profile URL")
        path = m.group(2).split("?")[0].split("#")[0].strip("/")
        handle = path.split("/")[0] if path else ""
    else:
        handle = v
    handle = handle.removeprefix("@")
    if not _HANDLE_RE.match(handle):
        raise ChannelError(f"must be a {LABELS[kind]} handle or profile URL")
    if kind == "github" and not m and "/" in v:
        raise ChannelError("must be a GitHub username or profile URL")
    return prefix + handle


def _whatsapp(v: str) -> str:
    m = _WA_RE.match(v)
    handle = (m.group(1).split("?")[0].strip("/") if m else v).removeprefix("@")
    if len(digits(handle)) >= 7:
        raise ChannelError(WHATSAPP_NUMBER_MSG)
    if not _HANDLE_RE.match(handle):
        raise ChannelError("Use your WhatsApp username, not your number.")
    return "@" + handle


def normalize(kind: str, value: str) -> str:
    """Validate ``value`` for ``kind`` and return its canonical stored form."""
    v = value.strip()
    if kind not in KINDS:
        raise ChannelError("unknown channel kind")
    if not v:
        raise ChannelError("value is required")
    if kind == "email":
        if not _EMAIL_RE.match(v):
            raise ChannelError("must be a valid email address")
        return v.lower()
    if kind == "phone":
        if not _PHONE_RE.match(v) or not 7 <= len(digits(v)) <= 15:
            raise ChannelError("must be a phone number with 7 to 15 digits")
        return v
    if kind == "whatsapp":
        return _whatsapp(v)
    if kind in HANDLE_KINDS:
        return _handle_from(kind, v)
    return _http_url(v)


def display(kind: str, value: str) -> str:
    if kind in ("instagram", "x", "telegram"):
        return "@" + value.rstrip("/").rsplit("/", 1)[-1]
    if kind in URL_KINDS or kind == "github":
        return re.sub(r"^https?://", "", value).rstrip("/")
    return value  # email, phone, whatsapp (already "@name")


def href(kind: str, value: str) -> str | None:
    if kind == "email":
        return f"mailto:{value}"
    if kind == "phone":
        return "tel:+" + digits(value) if value.lstrip().startswith("+") else "tel:" + digits(value)
    if kind == "whatsapp":
        return f"https://wa.me/{value.removeprefix('@')}"
    return value if _URL_RE.match(value) else None


@dataclass(frozen=True)
class Channel:
    kind: str
    label: str
    value: str
    share: bool

    @property
    def display(self) -> str:
        return display(self.kind, self.value)

    @property
    def href(self) -> str | None:
        return href(self.kind, self.value)


def from_items(items: list[dict]) -> list[Channel]:
    return [
        Channel(
            i.get("kind") or "website", i.get("label") or "", i.get("value") or "", bool(i["share"])
        )
        for i in items
        if i.get("value")
    ]


def variants(c: Channel) -> set[str]:
    """Every spelling of this channel's value the output guard must catch (lower-cased)."""
    v = c.value.strip()
    out = {v, c.display, c.href or ""}
    if c.kind == "phone":
        d = digits(v)
        out |= {d, "+" + d, re.sub(r"[\s().\-]", "", v)}
    elif c.kind in ("instagram", "x", "telegram", "whatsapp"):
        handle = v.rstrip("/").rsplit("/", 1)[-1].removeprefix("@")
        out |= {handle, "@" + handle}
    elif c.kind == "email":
        out.add(v.removeprefix("mailto:"))
    if re.match(r"^https?://", v, re.IGNORECASE):
        out.add(re.sub(r"^https?://", "", v).rstrip("/"))
    # Short strings would redact ordinary words; the phone/handle minimum is 4.
    return {s.lower() for s in out if len(s) >= 4}
