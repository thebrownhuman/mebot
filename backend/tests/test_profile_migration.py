import sqlalchemy as sa
from alembic import command

from mebot.db import alembic_config, run_migrations
from mebot.profile_legacy import copy_legacy_profiles

TABLES = {
    "profile_identity": True,
    "profile_links": False,
    "experiences": False,
    "educations": False,
    "skills": False,
    "projects": False,
    "interests": False,
    "faqs": False,
    "avoid_topics": False,
    "profile_notes": True,
}


def _seed_0004(url):
    command.upgrade(alembic_config(url), "0004")
    eng = sa.create_engine(url)
    with eng.begin() as c:
        c.execute(
            sa.text(
                "INSERT INTO bots (id, slug, name, created_at, updated_at, registration_consent, "
                "setup_completed_at) VALUES "
                "('b1', 'jane', 'Jane Doe', '2026-01-01', '2026-01-01', 0, '2026-01-02'),"
                "('b2', 'default', 'Default', '2026-01-01', '2026-01-01', 0, NULL)"
            )
        )
        c.execute(
            sa.text(
                "INSERT INTO profiles (id, bot_id, content, created_at, updated_at) VALUES "
                "('p1', 'b1', 'NAME: Jane\nSTACK: Go', '2026-01-01', '2026-01-01')"
            )
        )
    return eng


def test_0005_tables_shape(tmp_path):
    url = f"sqlite:///{(tmp_path / 'p.db').as_posix()}"
    run_migrations(url)
    insp = sa.inspect(sa.create_engine(url))
    tables = set(insp.get_table_names())
    assert set(TABLES) <= tables
    assert "profiles" not in tables and "legacy_profiles" in tables
    for t, singleton in TABLES.items():
        cols = {c["name"]: c for c in insp.get_columns(t)}
        assert {"id", "bot_id", "created_at", "updated_at", "deleted_at"} <= set(cols), t
        assert cols["deleted_at"]["nullable"] is True
        assert ("sort_order" in cols) is (not singleton), t
        ixs = insp.get_indexes(t)
        assert any(ix["column_names"] == ["bot_id", "deleted_at"] for ix in ixs), t
        if singleton:
            assert any(ix["unique"] and ix["column_names"] == ["bot_id"] for ix in ixs), t
        assert insp.get_foreign_keys(t) == []
    exp = {c["name"] for c in insp.get_columns("experiences")}
    assert {"company", "title", "start_month", "end_month", "highlights", "tech"} <= exp
    proj = {c["name"] for c in insp.get_columns("projects")}
    assert {"frontend", "backend", "infra", "data_ai", "repo_url", "live_url"} <= proj


def test_0005_copies_blob_to_notes_and_prefills_name(tmp_path):
    url = f"sqlite:///{(tmp_path / 'u.db').as_posix()}"
    eng = _seed_0004(url)
    run_migrations(url)
    with eng.connect() as c:
        notes = dict(c.execute(sa.text("SELECT bot_id, content FROM profile_notes")).all())
        names = dict(c.execute(sa.text("SELECT bot_id, full_name FROM profile_identity")).all())
        legacy = c.execute(sa.text("SELECT content FROM legacy_profiles")).scalar_one()
    assert notes == {"b1": "NAME: Jane\nSTACK: Go"}
    # Only set-up bots get a name: "Default" is a placeholder, not a person.
    assert names == {"b1": "Jane Doe"}
    assert legacy == "NAME: Jane\nSTACK: Go"


def test_legacy_copy_is_idempotent(tmp_path):
    url = f"sqlite:///{(tmp_path / 'i.db').as_posix()}"
    eng = _seed_0004(url)
    run_migrations(url)
    with eng.begin() as c:
        c.execute(sa.text("UPDATE profile_notes SET content = 'edited'"))
        copy_legacy_profiles(c)
        copy_legacy_profiles(c)
    with eng.connect() as c:
        assert c.execute(sa.text("SELECT COUNT(*) FROM profile_notes")).scalar_one() == 1
        assert c.execute(sa.text("SELECT COUNT(*) FROM profile_identity")).scalar_one() == 1
        assert c.execute(sa.text("SELECT content FROM profile_notes")).scalar_one() == "edited"


def test_0006_columns(tmp_path):
    url = f"sqlite:///{(tmp_path / 'g.db').as_posix()}"
    eng = _seed_0004(url)
    run_migrations(url)
    insp = sa.inspect(eng)
    ident = {c["name"]: c for c in insp.get_columns("profile_identity")}
    msgs = {c["name"]: c for c in insp.get_columns("messages")}
    for col in (ident["count_internships"], ident["count_freelance"], msgs["unanswered"]):
        assert col["nullable"] is False
    with eng.connect() as c:
        row = c.execute(
            sa.text("SELECT count_internships, count_freelance FROM profile_identity")
        ).one()
    assert (bool(row[0]), bool(row[1])) == (False, True)  # existing rows get defaults
