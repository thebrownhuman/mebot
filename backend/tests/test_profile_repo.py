import pytest
from pydantic import ValidationError

from mebot.db import make_session_factory, run_migrations
from mebot.profile.schemas import ExperienceIn, IdentityIn, LinkIn, NotesIn, ProjectIn
from mebot.profile.sections import SECTIONS, get_section
from mebot.repos import profile_items as repo


@pytest.fixture
def db(tmp_path):
    url = f"sqlite:///{(tmp_path / 'p.db').as_posix()}"
    run_migrations(url)
    with make_session_factory(url)() as s:
        yield s


def fields(exc: ValidationError) -> set[str]:
    return {".".join(str(p) for p in e["loc"]) for e in exc.errors()}


# --- registry ------------------------------------------------------------------


def test_sections_registry():
    assert set(SECTIONS) == {
        "links",
        "experiences",
        "educations",
        "skills",
        "projects",
        "interests",
        "faqs",
        "avoid-topics",
    }
    assert get_section("nope") is None
    assert get_section("projects").json_fields == ("highlights", "tech")


# --- validation ----------------------------------------------------------------


def exp(**over):
    base = {"company": "Acme", "title": "Engineer", "start_month": "2022-03"}
    return {**base, **over}


@pytest.mark.parametrize("month", ["2022-13", "2022-1", "22-01", "2022/01", "abc"])
def test_month_format(month):
    with pytest.raises(ValidationError) as e:
        ExperienceIn(**exp(start_month=month))
    assert "start_month" in fields(e.value)


def test_end_before_start_rejected_on_end_field():
    with pytest.raises(ValidationError) as e:
        ExperienceIn(**exp(end_month="2021-12"))
    assert fields(e.value) == {"end_month"}
    assert ExperienceIn(**exp(end_month="2022-03")).end_month == "2022-03"
    assert ExperienceIn(**exp()).end_month is None  # current job


@pytest.mark.parametrize("url", ["javascript:alert(1)", "ftp://x.com", "example.com", "http://"])
def test_urls_http_only(url):
    with pytest.raises(ValidationError) as e:
        LinkIn(label="x", url=url)
    assert "url" in fields(e.value)


def test_length_limits():
    with pytest.raises(ValidationError) as e:
        ExperienceIn(**exp(company="x" * 201))
    assert "company" in fields(e.value)
    with pytest.raises(ValidationError):
        ExperienceIn(**exp(description="x" * 5001))
    with pytest.raises(ValidationError):
        NotesIn(content="x" * 20001)
    NotesIn(content="x" * 20000)


def test_tag_lists():
    p = ProjectIn(name="mebot", summary="s", tech=[" Python ", "React"], highlights=[])
    assert p.tech == ["Python", "React"]
    with pytest.raises(ValidationError) as e:
        ProjectIn(name="m", summary="s", tech=["x"] * 31)
    assert "tech" in fields(e.value)
    with pytest.raises(ValidationError):
        ProjectIn(name="m", summary="s", tech=[""])


def test_required_and_blank_optional():
    with pytest.raises(ValidationError) as e:
        ExperienceIn(company="  ", title="t", start_month="2020-01")
    assert "company" in fields(e.value)
    assert ExperienceIn(**exp(location="  ")).location is None


def test_enums():
    with pytest.raises(ValidationError):
        ExperienceIn(**exp(employment_type="slavery"))
    assert ExperienceIn(**exp(employment_type="contract")).employment_type == "contract"


def test_identity_defaults_and_email():
    i = IdentityIn()
    assert i.full_name == "" and i.email_public is None
    with pytest.raises(ValidationError):
        IdentityIn(email_public="nope")
    with pytest.raises(ValidationError):
        IdentityIn(photo_url="javascript:x")


# --- repo ------------------------------------------------------------------------


def test_create_list_ordered_update_delete(db):
    sec = get_section("projects")
    a = repo.create(db, sec, "b1", ProjectIn(name="A", summary="a", tech=["Go"]))
    b = repo.create(db, sec, "b1", ProjectIn(name="B", summary="b"))
    db.commit()
    assert (a.sort_order, b.sort_order) == (0, 1)
    items = [repo.serialize(sec, r) for r in repo.list_items(db, sec, "b1")]
    assert [i["name"] for i in items] == ["A", "B"]
    assert items[0]["tech"] == ["Go"] and items[1]["highlights"] == []
    assert items[0]["created_at"].endswith("Z")
    assert "bot_id" not in items[0] and "deleted_at" not in items[0]

    repo.update(db, sec, a, ProjectIn(name="A2", summary="a2", tech=["Rust"]))
    db.commit()
    assert repo.get(db, sec, "b1", a.id).tech == '["Rust"]'

    repo.soft_delete(db, a)
    db.commit()
    assert [r.name for r in repo.list_items(db, sec, "b1")] == ["B"]
    assert repo.get(db, sec, "b1", a.id) is None


def test_bot_isolation(db):
    sec = get_section("faqs")
    from mebot.profile.schemas import FaqIn

    row = repo.create(db, sec, "b1", FaqIn(question="q", answer="a"))
    db.commit()
    assert repo.get(db, sec, "b2", row.id) is None
    assert repo.list_items(db, sec, "b2") == []


def test_reorder_requires_exact_id_set(db):
    sec = get_section("links")
    ids = [
        repo.create(db, sec, "b1", LinkIn(label=str(i), url="https://x.com")).id for i in range(3)
    ]
    other = repo.create(db, sec, "b2", LinkIn(label="o", url="https://x.com")).id
    db.commit()
    assert not repo.reorder(db, sec, "b1", ids[:2])
    assert not repo.reorder(db, sec, "b1", [*ids, other])
    assert not repo.reorder(db, sec, "b1", [ids[0], ids[0], ids[1]])
    assert [r.id for r in repo.list_items(db, sec, "b1")] == ids
    assert repo.reorder(db, sec, "b1", list(reversed(ids)))
    db.commit()
    assert [r.id for r in repo.list_items(db, sec, "b1")] == list(reversed(ids))


def test_singletons(db):
    assert repo.get_identity(db, "b1") is None
    repo.put_identity(db, "b1", IdentityIn(full_name="Jane", headline="Dev"))
    repo.put_identity(db, "b1", IdentityIn(full_name="Jane D"))
    repo.put_notes(db, "b1", NotesIn(content="hello"))
    db.commit()
    assert repo.get_identity(db, "b1").full_name == "Jane D"
    assert repo.get_identity(db, "b1").headline == ""  # PUT replaces
    assert repo.get_notes(db, "b1").content == "hello"
