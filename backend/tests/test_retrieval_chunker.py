from mebot import evals
from mebot.profile.data import ProfileData
from mebot.retrieval import chunker
from tests.retrieval_fixtures import large_profile


def test_one_chunk_per_item_with_heading_and_title():
    p = large_profile()
    chunks = chunker.build_chunks(p)
    by_sec = {}
    for c in chunks:
        by_sec.setdefault(c.section, []).append(c)
    assert len(by_sec["projects"]) == 40
    assert len(by_sec["experiences"]) == 10
    assert len(by_sec["faqs"]) == 1
    assert len(by_sec["learned"]) == 2
    c = by_sec["projects"][3]
    assert c.title == "Project GraphQL 3"
    assert c.text.startswith("[PROJECTS] Project GraphQL 3")
    assert "federated gateway" in c.text
    assert by_sec["experiences"][0].title == "Engineer level 0 at Company0"


def test_notes_split_near_300_tokens():
    chunks = [c for c in chunker.build_chunks(large_profile()) if c.section == "notes"]
    assert len(chunks) > 1
    for c in chunks:
        assert (len(c.text) + 3) // 4 <= 360  # ~300 tokens plus heading


def test_keys_unique_and_stable_and_hash_tracks_content():
    p = large_profile()
    a = chunker.build_chunks(p)
    b = chunker.build_chunks(large_profile())
    assert [(c.item_key, c.content_hash) for c in a] == [(c.item_key, c.content_hash) for c in b]
    assert len({c.item_key for c in a}) == len(a)
    p.items("projects")[0]["summary"] = "changed"
    c = chunker.build_chunks(p)
    changed = [x.item_key for x, y in zip(c, a, strict=True) if x.content_hash != y.content_hash]
    assert changed == ["projects:0"]


def test_db_ids_used_as_keys():
    p = large_profile()
    p.items("projects")[0]["id"] = "abc"
    assert "projects:abc" in {c.item_key for c in chunker.build_chunks(p)}


def test_skills_grouped_by_category():
    p = large_profile()
    chunks = [c for c in chunker.build_chunks(p) if c.section == "skills"]
    assert len(chunks) == 1 and "Python" in chunks[0].text and "Go" in chunks[0].text


def test_outline_lists_titles_not_details():
    text = chunker.outline(large_profile())
    assert "Engineer level 4 at Company4" in text
    assert "Project Kafka 0" in text
    assert "federated gateway" not in text


def test_empty_profile():
    assert chunker.build_chunks(ProfileData()) == []
    assert chunker.outline(ProfileData()) == ""


def test_sample_profile_chunks():
    chunks = chunker.build_chunks(evals.load_golden().profile)
    assert {c.section for c in chunks} >= {"experiences", "projects", "educations"}
