import pytest
from fastapi.testclient import TestClient

from mebot import cli
from mebot.main import create_app
from tests.conftest import ADMIN_EMAIL, do_setup

NEW = "reset password 123"


@pytest.fixture
def setup_done(settings):
    with TestClient(create_app(settings)) as c:
        assert do_setup(c).status_code == 201
    return settings


def run(settings, monkeypatch, argv, answers):
    it = iter(answers)
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(it))
    return cli.main(argv)


def login(client, password):
    return client.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": password})


def test_reset_password(setup_done, monkeypatch, capsys):
    app = create_app(setup_done)
    with TestClient(app) as old:
        assert login(old, "correct horse battery").status_code == 204
        rc = run(
            setup_done, monkeypatch, ["reset-password", "--email", "OWNER@example.com"], [NEW, NEW]
        )
        assert rc == 0
        assert old.get("/api/auth/me").status_code == 401  # sessions revoked
    with TestClient(app) as c:
        assert login(c, "correct horse battery").status_code == 401
        assert login(c, NEW).status_code == 204


def test_reset_unknown_email(setup_done, monkeypatch, capsys):
    rc = run(setup_done, monkeypatch, ["reset-password", "--email", "x@example.com"], [NEW, NEW])
    assert rc == 1
    assert "no admin" in capsys.readouterr().err.lower()


def test_reset_mismatch_and_short(setup_done, monkeypatch, capsys):
    assert (
        run(setup_done, monkeypatch, ["reset-password", "--email", ADMIN_EMAIL], [NEW, NEW + "x"])
        == 1
    )
    assert (
        run(setup_done, monkeypatch, ["reset-password", "--email", ADMIN_EMAIL], ["short", "short"])
        == 1
    )


def test_invite_create_hosted(hosted_settings, monkeypatch, capsys):
    from mebot.db import make_session_factory
    from mebot.repos import invites

    monkeypatch.setattr(cli, "Settings", lambda: hosted_settings)
    assert cli.main(["invite", "create", "--note", "for sam", "--days", "7"]) == 0
    code = capsys.readouterr().out.strip().rsplit(" ", 1)[-1]
    with make_session_factory(hosted_settings.database_url)() as db:
        assert invites.valid(db, code)


def test_invite_create_refused_in_single_mode(settings, monkeypatch, capsys):
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    assert cli.main(["invite", "create"]) == 1
    assert "MODE=hosted" in capsys.readouterr().err
