"""The owner's view and controls for the install registry ("mebot project")."""

import json

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from mebot.db import get_db
from mebot.deps import csrf_on_mutation, get_current_admin, get_current_bot, require_setup_done
from mebot.models import Bot
from mebot.repos import logs
from mebot.telemetry import identity, semver
from mebot.telemetry.service import Telemetry, contact_email, get_state, update_info

router = APIRouter(
    prefix="/api/admin/telemetry",
    dependencies=[
        Depends(require_setup_done),
        Depends(get_current_admin),
        Depends(csrf_on_mutation),
    ],
)


def _iso(dt) -> str | None:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def view(request: Request, db: Session, bot: Bot) -> dict:
    settings = request.app.state.settings
    tele: Telemetry = request.app.state.telemetry
    key: identity.InstallKey | None = request.app.state.install_key
    st = get_state(db)
    db.commit()
    upd = update_info(st, bot)
    if settings.telemetry != "on":  # nothing is checked any more: don't keep old banners alive
        upd = {**upd, "available": False, "dismissed": False, "advisory": None}
    adv = upd["advisory"]
    last = None
    if st.last_heartbeat_at and st.last_heartbeat_payload:
        last = {
            "sent_at": _iso(st.last_heartbeat_at),
            "payload": json.loads(st.last_heartbeat_payload),
        }
    return {
        "telemetry": settings.telemetry,
        "registry_url": settings.registry_url,
        "consent": bot.registration_consent,
        "status": tele.status(db, bot),
        "registered_at": _iso(st.registered_at),
        "last_register_error": st.last_register_error,
        "install_id_prefix": key.id_prefix if key else None,
        "update_contact_email": bot.update_contact_email,
        "effective_email": contact_email(db, bot),
        "public_url": settings.public_url,
        "last_heartbeat": last,
        "payload_preview": tele.client().heartbeat_payload() if key else None,
        "last_check_at": _iso(st.last_check_at),
        "update": {
            "current": upd["current"],
            "latest": upd["latest"],
            "available": upd["available"],
            "dismissed": upd["dismissed"],
            "unsupported": upd["unsupported"],
            "advisory": None
            if adv is None
            else {k: adv.get(k) for k in ("id", "severity", "title", "url")},
        },
    }


@router.get("")
def get_telemetry(
    request: Request, db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)
):
    return view(request, db, bot)


class TelemetryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consent: bool = None
    update_contact_email: str | None = Field(default=None, max_length=254)

    @field_validator("update_contact_email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        if not v:
            return None
        try:
            return validate_email(v, check_deliverability=False).normalized
        except EmailNotValidError:
            raise ValueError("not a valid e-mail address") from None


@router.put("")
def put_telemetry(
    req: TelemetryIn,
    request: Request,
    db: Session = Depends(get_db),
    bot: Bot = Depends(get_current_bot),
):
    sent = req.model_fields_set
    changed = []
    if "consent" in sent and req.consent is not None and req.consent != bot.registration_consent:
        bot.registration_consent = req.consent
        changed.append("consent")
    if "update_contact_email" in sent and req.update_contact_email != bot.update_contact_email:
        bot.update_contact_email = req.update_contact_email
        changed.append("contact_email")
    if changed:
        logs.add(db, bot.id, None, "telemetry_updated", detail=",".join(changed))
    db.commit()
    if changed:
        request.app.state.telemetry.nudge()  # register / unregister now, not at the next tick
    return view(request, db, bot)


class DismissIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(max_length=40)

    @field_validator("version")
    @classmethod
    def _v(cls, v: str) -> str:
        if not semver.valid(v):
            raise ValueError("not a version")
        return v


@router.post("/dismiss-update", status_code=204)
def dismiss_update(
    req: DismissIn, db: Session = Depends(get_db), bot: Bot = Depends(get_current_bot)
):
    bot.dismissed_update_version = req.version
    db.commit()
    return Response(status_code=204)
