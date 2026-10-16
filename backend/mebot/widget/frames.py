"""Who may frame what.

Every response gets ``X-Frame-Options: DENY`` + ``frame-ancestors 'self'`` unless the
route set its own CSP: the embed page sets ``frame-ancestors`` from the owner's
allowed sites (and no X-Frame-Options, which can't express a list).
"""

from mebot.models import WidgetSettings
from mebot.repos import widget as widget_repo
from mebot.widget.origins import OriginError, normalise

DEFAULT_CSP = "frame-ancestors 'self'"
NONE_CSP = "frame-ancestors 'none'"


def embed_csp(row: WidgetSettings | None) -> str:
    if row is None or not row.enabled:
        return NONE_CSP
    if row.allow_any_origin:
        return "frame-ancestors *"
    sources = ["'self'"]
    for raw in widget_repo.origins(row):
        try:  # re-check on the way out: this string is a header
            o = normalise(raw)
        except OriginError:
            continue
        if o not in sources:
            sources.append(o)
    return "frame-ancestors " + " ".join(sources)


async def frame_headers(request, call_next):
    response = await call_next(request)
    if "content-security-policy" not in response.headers:
        response.headers["Content-Security-Policy"] = DEFAULT_CSP
        response.headers.setdefault("X-Frame-Options", "DENY")
    return response


EMBED_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="referrer" content="no-referrer">
<title>Chat</title>
<link rel="stylesheet" href="/embed-app/embed.css">
</head>
<body>
<div id="root"></div>
<script type="module" src="/embed-app/embed.js"></script>
</body>
</html>
"""

UNAVAILABLE_HTML = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Unavailable</title>
<style>body{margin:0;font:14px system-ui,sans-serif;color:#555;
display:grid;place-items:center;height:100vh}</style>
</head>
<body><p>This chat is unavailable.</p></body>
</html>
"""
