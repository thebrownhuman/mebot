"""The plugin SDK's CDN files (packages/sdk, built to SDK_DIST).

/sdk/v1/mebot.js        latest 1.x, cached one day (the path to put in a page)
/sdk/<x.y.z>/mebot.js   that exact version, immutable for a year (only the one built)
"""

import re

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from mebot.errors import ApiError

router = APIRouter()
LATEST_CACHE = "public, max-age=86400"
IMMUTABLE = "public, max-age=31536000, immutable"
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


@router.get("/sdk/{version}/mebot.js")
def sdk(version: str, request: Request):
    dist = request.app.state.settings.sdk_dist
    path = dist / "mebot.js"
    if not path.is_file():
        raise ApiError(404, "NOT_BUILT", "SDK not built (cd packages/sdk && npm run build)")
    if version == "v1":
        cache = LATEST_CACHE
    else:
        try:
            built = (dist / "VERSION").read_text(encoding="utf-8").strip()
        except OSError:
            built = ""
        if not SEMVER.match(version) or version != built:
            raise ApiError(404, "NOT_FOUND", "Not Found")
        cache = IMMUTABLE
    return FileResponse(
        path,
        media_type="text/javascript",
        headers={"Cache-Control": cache, "Access-Control-Allow-Origin": "*"},
    )
