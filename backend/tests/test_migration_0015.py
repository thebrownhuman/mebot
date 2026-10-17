import sqlalchemy as sa

from mebot.db import run_migrations


def test_0015_adds_telemetry_state_and_bot_columns(tmp_path):
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    run_migrations(url)
    insp = sa.inspect(sa.create_engine(url))
    state = {c["name"]: c for c in insp.get_columns("telemetry_state")}
    assert set(state) >= {
        "id",
        "registered_at",
        "last_register_error",
        "last_heartbeat_at",
        "last_check_at",
        "latest_version",
        "advisories",
        "created_at",
        "updated_at",
    }
    assert state["advisories"]["nullable"] is False
    bots = {c["name"]: c for c in insp.get_columns("bots")}
    assert bots["update_contact_email"]["nullable"] is True
    assert bots["dismissed_update_version"]["nullable"] is True
    run_migrations(url)  # re-running is a no-op
