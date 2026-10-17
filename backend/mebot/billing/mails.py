"""Owner billing mails (15a mailer): trial running out, trial ended, long inactivity."""

import asyncio

from mebot.hosted import mailer
from mebot.hosted.mailer import Mail


def _billing_link(settings) -> str:
    base = (settings.public_url or "").rstrip("/")
    return f"{base}/admin/billing" if base else "Admin -> Billing"


def build(key: str, to: str, settings) -> Mail:
    link = _billing_link(settings)
    if key == "trial_3days":
        return Mail(
            to,
            "Your mebot trial ends in 3 days",
            f"Your free trial ends in 3 days. Subscribe to keep your assistant online:\n\n{link}",
        )
    if key == "trial_msg80":
        return Mail(
            to,
            "You've used 80% of your mebot trial messages",
            f"Your assistant has answered 80% of the {settings.trial_messages} trial messages. "
            f"Subscribe to keep it online when they run out:\n\n{link}",
        )
    if key == "trial_ended":
        return Mail(
            to,
            "Your mebot trial has ended",
            "Your free trial has ended, so your assistant is offline for visitors. Your data is "
            f"kept. Subscribe any time to put it back online:\n\n{link}",
        )
    if key == "inactive_90":
        return Mail(
            to,
            "Your mebot assistant has been offline for 90 days",
            "Your assistant has been offline for 90 days. Your data is still kept and nothing "
            "is deleted automatically. Subscribe to put it back online, or delete your account "
            f"from the Account page if you no longer need it:\n\n{link}",
        )
    raise KeyError(key)


def send_later(app, db, bot_id: str, key: str) -> None:
    """Fire-and-forget from a request (the chat stream mustn't wait on SMTP)."""
    from mebot.billing import service

    to = service.owner_email(db, bot_id)
    if not to:
        return
    task = asyncio.get_running_loop().create_task(
        mailer.deliver(app.state.mailer, build(key, to, app.state.settings))
    )
    pending = app.state.billing_tasks
    pending.add(task)
    task.add_done_callback(pending.discard)
