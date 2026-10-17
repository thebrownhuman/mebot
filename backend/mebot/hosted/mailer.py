"""Platform mail (hosted mode): verification, password reset, approval notices.

Without SMTP_HOST mail goes to the log (development); tests swap in a capturing mailer.
Sending is best-effort from the caller's point of view: a failed send is logged, never
shown to the visitor (the reset/verify endpoints answer the same either way).
"""

import asyncio
import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage

log = logging.getLogger("mebot.mail")


@dataclass(frozen=True)
class Mail:
    to: str
    subject: str
    body: str


class ConsoleMailer:
    def __init__(self):
        self.sent: list[Mail] = []

    async def send(self, mail: Mail) -> None:
        self.sent.append(mail)
        log.info("mail to=%s subject=%r\n%s", mail.to, mail.subject, mail.body)


class SmtpMailer:
    def __init__(self, settings):
        self.s = settings

    def _send_sync(self, mail: Mail) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.s.smtp_from, mail.to, mail.subject
        msg.set_content(mail.body)
        ctx = ssl.create_default_context()
        if self.s.smtp_port == 465:
            server = smtplib.SMTP_SSL(self.s.smtp_host, self.s.smtp_port, context=ctx, timeout=20)
        else:
            server = smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=20)
        with server:
            if self.s.smtp_port != 465:
                server.starttls(context=ctx)
            if self.s.smtp_user:
                server.login(self.s.smtp_user, self.s.smtp_password or "")
            server.send_message(msg)

    async def send(self, mail: Mail) -> None:
        await asyncio.to_thread(self._send_sync, mail)


def make_mailer(settings):
    return SmtpMailer(settings) if settings.smtp_host else ConsoleMailer()


async def deliver(mailer, mail: Mail) -> None:
    try:
        await mailer.send(mail)
    except Exception:  # never surfaces to the requester; see module docstring
        log.exception("sending mail to %s failed", mail.to)


# --- Templates ----------------------------------------------------------------------


def verify_mail(to: str, link: str) -> Mail:
    return Mail(
        to,
        "Confirm your e-mail for mebot",
        f"Confirm your e-mail address to put your assistant online:\n\n{link}\n\n"
        "The link works for 24 hours. If you didn't sign up, ignore this message.",
    )


def reset_mail(to: str, link: str) -> Mail:
    return Mail(
        to,
        "Reset your mebot password",
        f"Choose a new password here:\n\n{link}\n\n"
        "The link works once, for 30 minutes. If you didn't ask for it, ignore this message.",
    )


def already_registered_mail(to: str, login_link: str, reset_link: str) -> Mail:
    return Mail(
        to,
        "You already have a mebot account",
        "Someone (hopefully you) tried to sign up with this address, which already has an "
        f"account.\n\nLog in: {login_link}\nForgot your password? {reset_link}",
    )


def approved_mail(to: str, login_link: str) -> Mail:
    return Mail(
        to,
        "Your mebot account is approved",
        f"Your sign-up was approved. Log in to set up your assistant:\n\n{login_link}",
    )
