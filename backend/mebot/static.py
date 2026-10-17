"""Serve the built frontend from the API process (single-image deploys).

Cache policy by path class:
- ``/assets/*``   content-hashed chunks -> immutable for a year
- ``/embed-app/*`` fixed names the embed page references -> no-cache (revalidate)
- ``/widget/v1.js`` served by routes/widget.py -> one day
- ``index.html`` and the SPA fallback -> no-cache
Unknown ``/api/*``, ``/assets/*`` and ``/embed-app/*`` paths stay 404s; any other GET that
isn't a file falls back to ``index.html`` so client-side routes (``/admin/...``) load.
"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from mebot.errors import ApiError

IMMUTABLE = "public, max-age=31536000, immutable"
NO_CACHE = "no-cache"
ROOT_FILE_CACHE = "public, max-age=3600"
NO_FALLBACK = ("api/", "assets/", "embed-app/", "widget/", "embed/")


class _CachedStatic(StaticFiles):
    def __init__(self, *, directory: Path, cache_control: str):
        super().__init__(directory=directory)
        self.cache_control = cache_control

    async def get_response(self, path: str, scope: Scope):
        resp = await super().get_response(path, scope)
        if resp.status_code < 400:
            resp.headers["Cache-Control"] = self.cache_control
        return resp


def mount_frontend(app: FastAPI, dist: Path) -> None:
    for prefix, cache in (("assets", IMMUTABLE), ("embed-app", NO_CACHE)):
        d = dist / prefix
        if d.is_dir():
            app.mount(f"/{prefix}", _CachedStatic(directory=d, cache_control=cache), name=prefix)

    index = dist / "index.html"
    if not index.is_file():
        return
    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str, request: Request):
        if path.startswith(NO_FALLBACK) or path == "api":
            raise ApiError(404, "NOT_FOUND", "Not Found")
        if path:
            candidate = (root / path).resolve()
            if candidate.is_relative_to(root) and candidate.is_file() and candidate != index:
                return FileResponse(candidate, headers={"Cache-Control": ROOT_FILE_CACHE})
        return FileResponse(index, media_type="text/html", headers={"Cache-Control": NO_CACHE})
