"""Allowed-site rules for the widget.

An origin is ``scheme://host[:port]``: https only, except plain http on localhost /
127.0.0.1 for local testing. ``https://*.example.com`` allows exactly one subdomain
level. Values end up inside a CSP header, so the grammar is strict.
"""

import re

MAX_ORIGINS = 20

_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_HOST = re.compile(rf"^(?:\*\.)?{_LABEL}(?:\.{_LABEL})*$")
_ORIGIN = re.compile(r"^(https?)://([^/?#@:\s]+)(?::(\d{1,5}))?/?$")
_LOCAL = ("localhost", "127.0.0.1")
_DEFAULT_PORT = {"http": 80, "https": 443}


class OriginError(ValueError):
    pass


def normalise(raw: str) -> str:
    value = (raw or "").strip()
    m = _ORIGIN.match(value.lower())
    if not m:
        raise OriginError("use scheme://host[:port] with no path, e.g. https://example.com")
    scheme, host, port = m.group(1), m.group(2), m.group(3)
    if not _HOST.match(host):
        raise OriginError(f"invalid host: {host}")
    if host.startswith("*.") and host.count(".") < 2:
        raise OriginError("a wildcard needs a domain, e.g. https://*.example.com")
    if scheme == "http" and host not in _LOCAL:
        raise OriginError("https is required (http only for localhost)")
    out = f"{scheme}://{host}"
    if port is not None:
        n = int(port)
        if not 0 < n < 65536:
            raise OriginError("invalid port")
        if n != _DEFAULT_PORT[scheme]:
            out += f":{n}"
    return out


def validate_list(values: list[str]) -> list[str]:
    out: list[str] = []
    for v in values:
        o = normalise(v)
        if o not in out:
            out.append(o)
    if len(out) > MAX_ORIGINS:
        raise OriginError(f"at most {MAX_ORIGINS} sites")
    return out


def matches(origin: str | None, allowed: list[str]) -> bool:
    """True when a concrete origin (no wildcard) is covered by the allowed list."""
    try:
        o = normalise(origin or "")
    except OriginError:
        return False
    if "*" in o:
        return False
    scheme, rest = o.split("://", 1)
    for a in allowed:
        if a == o:
            return True
        a_scheme, a_rest = a.split("://", 1)
        if a_scheme == scheme and a_rest.startswith("*."):
            suffix = a_rest[1:]  # ".example.com[:port]"
            if rest.endswith(suffix):
                label = rest[: -len(suffix)]
                if label and "." not in label:
                    return True
    return False
