"""Standard error shape: {"error": {"code", "message", "status", "details?"}}."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: list[dict] | None = None,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers


def error_body(status: int, code: str, message: str, details: list[dict] | None = None) -> dict:
    err: dict = {"code": code, "message": message, "status": status}
    if details:
        err["details"] = details
    return {"error": err}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse(
            error_body(exc.status, exc.code, exc.message, exc.details),
            status_code=exc.status,
            headers=exc.headers,
        )
