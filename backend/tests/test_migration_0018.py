import sqlalchemy as sa

from mebot.db import run_migrations


def _cols(insp, table):
    return {c["name"]: c for c in insp.get_columns(table)}


def test_0018_adds_tenancy_columns_and_tables(tmp_path):
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    run_migrations(url, secret_key="k")
    insp = sa.inspect(sa.create_engine(url))

    bots = _cols(insp, "bots")
    assert bots["public_key"]["nullable"] is False
    assert bots["status"]["nullable"] is False
    assert bots["plan"]["nullable"] is False
    assert "status_reason" in bots
    assert "deletion_requested_at" in bots
    assert any(i["name"] == "ux_bots_public_key" and i["unique"] for i in insp.get_indexes("bots"))

    assert "email_verified_at" in _cols(insp, "admins")
    assert "bot_id" in _cols(insp, "admin_sessions")

    for table in ("password_resets", "email_verifications"):
        cols = _cols(insp, table)
        assert set(cols) >= {"id", "admin_id", "created_at", "expires_at", "used_at"}
    assert set(_cols(insp, "invites")) >= {
        "id", "code_hash", "created_at", "expires_at", "used_at", "used_by_admin_id", "deleted_at",
    }
    assert set(_cols(insp, "slug_redirects")) >= {"id", "old_slug", "bot_id", "expires_at"}
    run_migrations(url, secret_key="k")  # re-running is a no-op


def test_0018_backfills_existing_rows(tmp_path):
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    run_migrations(url, secret_key="k", revision="0016")
    eng = sa.create_engine(url)
    with eng.begin() as c:
        for i, slug in enumerate(("one", "two")):
            c.execute(
                sa.text(
                    "INSERT INTO bots (id, slug, name, created_at, updated_at, timezone,"
                    " registration_consent) VALUES (:id, :slug, 'n', '2026-01-01', '2026-01-01',"
                    " 'UTC', 0)"
                ),
                {"id": f"b{i}", "slug": slug},
            )
        c.execute(
            sa.text(
                "INSERT INTO admins (id, email, password_hash, created_at, updated_at)"
                " VALUES ('a1', 'o@x.io', 'h', '2026-01-02', '2026-01-02')"
            )
        )
    run_migrations(url, secret_key="k")
    with eng.connect() as c:
        rows = c.execute(sa.text("SELECT public_key, status, plan FROM bots")).all()
        verified = c.execute(sa.text("SELECT email_verified_at FROM admins")).scalar()
    keys = {r[0] for r in rows}
    assert len(keys) == 2 and all(k.startswith("pk_") for k in keys)
    assert {(r[1], r[2]) for r in rows} == {("active", "free")}
    assert verified is not None  # existing owners count as verified
