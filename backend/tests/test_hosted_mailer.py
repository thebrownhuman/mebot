import asyncio
import logging

from mebot.hosted import mailer as m


class _Settings:
    smtp_host = "smtp.invalid"
    smtp_port = 587
    smtp_user = "u"
    smtp_password = "p"
    smtp_from = "mebot <no-reply@x.io>"


def test_console_mailer_records_and_logs(caplog):
    mm = m.ConsoleMailer()
    with caplog.at_level(logging.INFO, "mebot.mail"):
        asyncio.run(mm.send(m.verify_mail("o@x.io", "https://x/verify?t=1")))
    assert mm.sent[0].to == "o@x.io" and "https://x/verify?t=1" in mm.sent[0].body
    assert "o@x.io" in caplog.text


def test_make_mailer_picks_smtp_only_with_host():
    assert isinstance(m.make_mailer(_Settings()), m.SmtpMailer)
    s = _Settings()
    s.smtp_host = None
    assert isinstance(m.make_mailer(s), m.ConsoleMailer)


def test_smtp_mailer_starttls_login_send(monkeypatch):
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            calls.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context):
            calls.append(("starttls",))

        def login(self, u, p):
            calls.append(("login", u, p))

        def send_message(self, msg):
            calls.append(("send", msg["To"], msg["Subject"]))

    monkeypatch.setattr(m.smtplib, "SMTP", FakeSMTP)
    asyncio.run(m.SmtpMailer(_Settings()).send(m.reset_mail("o@x.io", "L")))
    assert [c[0] for c in calls] == ["connect", "starttls", "login", "send"]
    assert calls[-1][1] == "o@x.io"


def test_deliver_swallows_failures(caplog):
    class Boom:
        async def send(self, mail):
            raise OSError("down")

    asyncio.run(m.deliver(Boom(), m.approved_mail("o@x.io", "L")))
    assert "failed" in caplog.text


def test_templates_carry_links():
    for mail in (
        m.verify_mail("a@x.io", "LINK1"),
        m.reset_mail("a@x.io", "LINK1"),
        m.approved_mail("a@x.io", "LINK1"),
        m.already_registered_mail("a@x.io", "LINK1", "LINK2"),
    ):
        assert "LINK1" in mail.body and mail.subject
