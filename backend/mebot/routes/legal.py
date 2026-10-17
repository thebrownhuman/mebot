"""GET /legal/{terms,privacy,refunds}: the platform's legal pages (hosted mode only).

Plain text from LEGAL_DIR. The bundled files are templates that must be reviewed by a
lawyer before launch; the operator replaces them (mount their own LEGAL_DIR).
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse

from mebot.errors import ApiError
from mebot.routes.hosted_accounts import require_hosted

router = APIRouter(dependencies=[Depends(require_hosted)])
DOCS = ("terms", "privacy", "refunds")


@router.get("/legal/{name}", response_class=PlainTextResponse)
def legal(name: str, request: Request):
    if name not in DOCS:
        raise ApiError(404, "NOT_FOUND", "Not Found")
    path = request.app.state.settings.legal_dir / f"{name}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        raise ApiError(404, "NOT_FOUND", "Not Found") from None
    return PlainTextResponse(text, headers={"Cache-Control": "public, max-age=3600"})
