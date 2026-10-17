import sqlalchemy as sa

from mebot.db import run_migrations


def test_0019_platform_tables(tmp_path):
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    run_migrations(url, secret_key="k")
    insp = sa.inspect(sa.create_engine(url))
    assert {"id", "email", "password_hash"} <= {
        c["name"] for c in insp.get_columns("platform_admins")
    }
    assert {"platform_admin_id", "expires_at"} <= {
        c["name"] for c in insp.get_columns("platform_sessions")
    }
    assert {"actor_id", "action", "target_bot_id", "detail"} <= {
        c["name"] for c in insp.get_columns("platform_audit")
    }
    assert "approved_at" in {c["name"] for c in insp.get_columns("bots")}
    run_migrations(url, secret_key="k")
