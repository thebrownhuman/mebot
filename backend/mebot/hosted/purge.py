"""Hard purge of deleted tenants (hosted mode), daily with retention.

A tenant that asked for deletion is offline at once (status=deleted) and erased here
once the grace period has passed: every row in every table with a ``bot_id`` column
(found from the metadata, so new tenant tables are covered), the owner and their tokens.
Expired slug redirects and account tokens are dropped too.
"""

import logging
from datetime import datetime

from sqlalchemy import delete, select

from mebot.models import (
    Admin,
    Base,
    Bot,
    EmailVerification,
    PasswordReset,
    SlugRedirect,
    utcnow,
)
from mebot.repos import account_tokens

log = logging.getLogger("mebot.hosted.purge")


def purge_deleted(session_factory, grace, now: datetime | None = None) -> int:
    now = now or utcnow()
    tenant_tables = [
        t for t in Base.metadata.sorted_tables if "bot_id" in t.c and t.name != "admins"
    ]
    purged = 0
    with session_factory() as db:
        due = db.scalars(
            select(Bot.id).where(
                Bot.deletion_requested_at.is_not(None), Bot.deletion_requested_at <= now - grace
            )
        ).all()
        for bot_id in due:
            admin_ids = db.scalars(select(Admin.id).where(Admin.bot_id == bot_id)).all()
            for table in tenant_tables:
                db.execute(delete(table).where(table.c.bot_id == bot_id))
            for model in (PasswordReset, EmailVerification):
                db.execute(delete(model).where(model.admin_id.in_(admin_ids)))
            db.execute(delete(Admin).where(Admin.bot_id == bot_id))
            db.execute(delete(Bot).where(Bot.id == bot_id))
            db.commit()
            purged += 1
        db.execute(delete(SlugRedirect).where(SlugRedirect.expires_at <= now))
        account_tokens.purge(db, now)
        db.commit()
    if purged:
        log.info("purged %d deleted tenant(s)", purged)
    return purged
