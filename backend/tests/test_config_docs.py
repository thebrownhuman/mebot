from mebot.config import REPO_ROOT, Settings, settings_markdown


def test_every_setting_is_documented():
    md = settings_markdown()
    for name in Settings.model_fields:
        assert f"`{name.upper()}`" in md
    assert "SQLAlchemy" not in md or "DATABASE_URL" in md
    assert "Defaults to sqlite:///<data_dir>/mebot.db" in md


def test_defaults_are_portable():
    md = settings_markdown()
    # Paths render relative to the repo, never this machine's absolute path.
    assert str(REPO_ROOT) not in md and "backend/data" in md


def test_checked_in_doc_is_up_to_date():
    doc = (REPO_ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")
    assert doc == settings_markdown(), (
        "run: python -m mebot.config --markdown > ../docs/configuration.md"
    )
