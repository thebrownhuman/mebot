import json

import pytest

from mebot.db import make_session_factory
from mebot.repos import retrieval as repo
from mebot.retrieval import chunker
from tests.retrieval_fixtures import large_profile


@pytest.fixture
def db(settings):
    with make_session_factory(settings.database_url)() as s:
        yield s


def test_sync_is_incremental(db):
    p = large_profile()
    first = repo.sync(db, "b1", chunker.build_chunks(p))
    db.commit()
    assert first["added"] == len(chunker.build_chunks(p)) and first["updated"] == 0
    # give one chunk a vector, then re-sync unchanged: nothing moves, vector survives
    row = repo.rows(db, "b1")["projects:0"]
    row.embedding, row.embedding_model = b"\x00\x00\x80?", "m"
    db.commit()
    again = repo.sync(db, "b1", chunker.build_chunks(p))
    assert again == {"added": 0, "updated": 0, "removed": 0}
    assert repo.rows(db, "b1")["projects:0"].embedding == b"\x00\x00\x80?"
    # change one item: only that chunk updates and loses its vector
    p.items("projects")[0]["summary"] = "brand new summary"
    changed = repo.sync(db, "b1", chunker.build_chunks(p))
    db.commit()
    assert changed == {"added": 0, "updated": 1, "removed": 0}
    assert repo.rows(db, "b1")["projects:0"].embedding is None
    # drop an item
    p.sections["projects"].pop()
    assert repo.sync(db, "b1", chunker.build_chunks(p))["removed"] == 1


def test_is_stale(db):
    chunks = chunker.build_chunks(large_profile())
    assert repo.is_stale(repo.rows(db, "b1"), chunks)
    repo.sync(db, "b1", chunks)
    db.commit()
    assert not repo.is_stale(repo.rows(db, "b1"), chunks)
    p = large_profile()
    p.learned.append("a new fact")
    assert repo.is_stale(repo.rows(db, "b1"), chunker.build_chunks(p))


def test_bot_isolation(db):
    repo.sync(db, "b1", chunker.build_chunks(large_profile()))
    db.commit()
    assert repo.count(db, "b2") == 0 and repo.rows(db, "b2") == {}


def test_titles_skips_missing_ids(db):
    repo.sync(db, "b1", chunker.build_chunks(large_profile()))
    db.commit()
    row = repo.rows(db, "b1")["projects:0"]
    out = repo.titles(db, "b1", json.dumps([row.id, "gone"]))
    assert out == [{"id": row.id, "section": "projects", "title": "Project Kafka 0"}]
    assert repo.titles(db, "b1", None) == [] and repo.titles(db, "b1", "not json") == []


def test_settings_defaults(db):
    s = repo.get_or_create_settings(db, "b1")
    assert (s.mode, s.embeddings_enabled, s.embedding_model) == ("auto", False, None)
    assert repo.get_or_create_settings(db, "b1").id == s.id
