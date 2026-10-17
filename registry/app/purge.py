"""Retention: installs unseen for 180 days (and their registrations) are deleted."""

from datetime import datetime, timedelta

from app.config import Settings
from app.db import Database, iso

NOTIFICATION_KEEP_DAYS = 30


def run(db: Database, settings: Settings, now: datetime) -> dict[str, int]:
    cutoff = iso(now - timedelta(days=settings.purge_after_days))
    old_notes = iso(now - timedelta(days=NOTIFICATION_KEEP_DAYS))
    with db.tx() as c:
        stale = [
            r["install_id"]
            for r in c.execute("SELECT install_id FROM installs WHERE last_seen < ?", (cutoff,))
        ]
        regs = 0
        for install_id in stale:
            regs += c.execute(
                "DELETE FROM registrations WHERE install_id = ?", (install_id,)
            ).rowcount
            c.execute("DELETE FROM installs WHERE install_id = ?", (install_id,))
        nonces = c.execute("DELETE FROM nonces WHERE expires_at < ?", (iso(now),)).rowcount
        notes = c.execute(
            "DELETE FROM notifications WHERE status IN ('sent', 'dead') AND updated_at < ?",
            (old_notes,),
        ).rowcount
    return {"installs": len(stale), "registrations": regs, "nonces": nonces, "notifications": notes}
