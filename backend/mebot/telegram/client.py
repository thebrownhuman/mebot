"""Minimal Telegram Bot API client (httpx).

The bot token is part of every URL, so it must never reach a log or an error:
httpx exceptions are mapped to typed errors *without* their text (it contains the
URL) and Telegram's descriptions go through the shared ``scrub``.
"""

import logging
import re
from typing import Literal

import httpx

from mebot.llm.base import scrub

API = "https://api.telegram.org"
TIMEOUT = 10.0
POLL_SECONDS = 25

_TOKEN_IN_URL = re.compile(r"/bot\d+:[A-Za-z0-9_-]+")


class _RedactBotToken(logging.Filter):
    """httpx logs every request URL at INFO; the token is in the path."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if "/bot" in msg:
            record.msg, record.args = _TOKEN_IN_URL.sub("/bot[redacted]", msg), None
        return True


for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).addFilter(_RedactBotToken())

TgErrorKind = Literal["auth", "rate_limit", "bad_request", "server", "timeout", "unreachable"]


class TelegramError(Exception):
    """A Bot API call failed. ``message`` is safe to show the owner (token scrubbed)."""

    def __init__(
        self,
        kind: TgErrorKind,
        message: str,
        status: int | None = None,
        retry_after: int | None = None,
    ):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.status = status
        self.retry_after = retry_after


class TelegramClient:
    def __init__(self, token: str, base_url: str = API):
        self._token = token
        self._base = f"{base_url.rstrip('/')}/bot{token}"

    def __repr__(self) -> str:
        return "TelegramClient(token=[redacted])"

    async def _call(self, method: str, payload: dict | None = None, timeout: float = TIMEOUT):
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.post(f"{self._base}/{method}", json=payload or {})
        except httpx.TimeoutException:
            raise TelegramError("timeout", "Timed out contacting Telegram.") from None
        except Exception as e:  # noqa: BLE001 - message would include the token URL
            raise TelegramError(
                "unreachable", f"Cannot reach Telegram ({type(e).__name__})."
            ) from None
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code < 400 and data.get("ok"):
            return data.get("result")
        status = data.get("error_code") or r.status_code
        desc = scrub(str(data.get("description") or "")[:200], [self._token])
        if status in (401, 404):  # Telegram answers 404 for an unknown/revoked token
            raise TelegramError("auth", "Telegram rejected the bot token.", status)
        if status == 429:
            retry = (data.get("parameters") or {}).get("retry_after")
            raise TelegramError(
                "rate_limit", "Telegram rate limited the request.", status, int(retry or 1)
            )
        if status >= 500:
            raise TelegramError("server", f"Telegram server error ({status}).", status)
        raise TelegramError("bad_request", f"Telegram rejected the request: {desc}", status)

    async def get_me(self) -> dict:
        return await self._call("getMe")

    async def send_message(
        self,
        chat_id: str,
        text: str,
        *,
        reply_markup: dict | None = None,
        force_reply: bool = False,
        reply_to: int | None = None,
    ) -> int:
        payload: dict = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if force_reply:
            payload["reply_markup"] = {"force_reply": True}
        elif reply_markup:
            payload["reply_markup"] = reply_markup
        if reply_to is not None:
            payload["reply_parameters"] = {
                "message_id": reply_to,
                "allow_sending_without_reply": True,
            }
        result = await self._call("sendMessage", payload)
        return int(result["message_id"])

    async def answer_callback_query(self, callback_id: str, text: str | None = None) -> None:
        payload: dict = {"callback_query_id": callback_id}
        if text:
            payload["text"] = text
        await self._call("answerCallbackQuery", payload)

    async def edit_reply_markup(self, chat_id: str, message_id: int, reply_markup: dict) -> None:
        await self._call(
            "editMessageReplyMarkup",
            {"chat_id": chat_id, "message_id": message_id, "reply_markup": reply_markup},
        )

    async def get_updates(self, offset: int | None = None, timeout: int = POLL_SECONDS) -> list:
        payload: dict = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            payload = {"offset": offset, **payload}
        return await self._call("getUpdates", payload, timeout=timeout + 10) or []

    async def set_webhook(self, url: str, secret: str) -> None:
        await self._call(
            "setWebhook",
            {
                "url": url,
                "secret_token": secret,
                "allowed_updates": ["message", "callback_query"],
            },
        )

    async def delete_webhook(self) -> None:
        await self._call("deleteWebhook", {"drop_pending_updates": False})

    async def set_my_commands(self, commands: list[tuple[str, str]]) -> None:
        await self._call(
            "setMyCommands",
            {"commands": [{"command": c, "description": d} for c, d in commands]},
        )
