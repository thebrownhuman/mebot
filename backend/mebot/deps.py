"""Request-scoped dependencies."""

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from mebot.config import Settings
from mebot.db import get_db
from mebot.models import Bot
from mebot.repos import bots


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_current_bot(db: Session = Depends(get_db)) -> Bot:
    """Single mode: always the default bot (created on first use).

    Hosted mode will resolve the bot from the request (slug/host) in a later feature.
    """
    return bots.get_or_create_default(db)


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
