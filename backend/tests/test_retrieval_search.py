import sqlite3

import pytest

from mebot.retrieval import chunker, search
from tests.retrieval_fixtures import large_profile


def test_fts5_is_available():
    con = sqlite3.connect(":memory:")
    try:
        con.execute("create virtual table t using fts5(a)")
    except sqlite3.OperationalError as e:  # pragma: no cover - environment problem
        pytest.fail(f"This Python's sqlite3 was built without FTS5 ({e}); retrieval needs it.")


def _chunks():
    return chunker.build_chunks(large_profile())


def _titles(chunks, idx):
    return [chunks[i].title for i in idx]


def test_lexical_ranks_the_targeted_item_first():
    chunks = _chunks()
    r = search.lexical_rank(chunks, "Tell me about the Elasticsearch relevance work")
    assert _titles(chunks, r)[0].startswith("Project Elasticsearch")
    r = search.lexical_rank(
        chunks, "what did sam do at the unique-widget-7 platform?", search.name_terms("Sam Large")
    )
    assert _titles(chunks, r)[0] == "Engineer level 7 at Company7"


def test_lexical_stems_and_ignores_stopwords():
    chunks = _chunks()
    assert search.lexical_rank(chunks, "the a of and") == []
    assert search.lexical_rank(chunks, "kafka streaming ingestion pipelines")


def test_lexical_survives_odd_input():
    chunks = _chunks()
    for q in ['"', "AND OR NOT", "foo*", "(((", "a:b", "x" * 5000, "\U0001f600"]:
        search.lexical_rank(chunks, q)  # must not raise


def test_no_match_returns_empty():
    assert search.lexical_rank(_chunks(), "zzzqqq") == []


def test_query_merges_previous_user_message():
    assert search.build_query("what stack did it use?", "Tell me about Project Kafka 0") == (
        "what stack did it use? Tell me about Project Kafka 0"
    )
    assert search.build_query("hi", None) == "hi"
    chunks = _chunks()
    q = search.build_query("what stack did it use?", "Tell me about the Elasticsearch project")
    assert _titles(chunks, search.lexical_rank(chunks, q))[0].startswith("Project Elasticsearch")


def test_rrf_fuses_rankings():
    assert search.rrf([1, 2], [3, 2])[:1] == [2]  # best on both lists
    assert search.rrf([1, 2], []) == [1, 2]
    assert set(search.rrf([1], [2])) == {1, 2}


def test_cosine_rank():
    vecs = {0: [1.0, 0.0], 1: [0.0, 1.0], 2: [0.9, 0.1]}
    ranked = search.cosine_rank([1.0, 0.0], vecs)
    assert [i for i, _ in ranked] == [0, 2, 1]
    assert search.cosine_rank([0.0, 0.0], vecs) == []


def test_vector_roundtrip():
    v = [0.5, -1.25, 3.0]
    assert search.unpack(search.pack(v)) == v


def test_select_budget_min_keep_and_profile_order():
    chunks = _chunks()
    ranked = list(range(len(chunks) - 1, -1, -1))  # worst-first order, to prove reordering
    picked = search.select(chunks, ranked, budget_tokens=10_000, min_keep=3)
    assert [chunks[i].order for i in picked] == sorted(chunks[i].order for i in picked)
    assert sum(chunks[i].tokens for i in picked) <= 10_000 + max(c.tokens for c in chunks)
    tiny = search.select(chunks, ranked, budget_tokens=1, min_keep=3)
    assert len(tiny) == 3 and set(tiny) == set(ranked[:3])
    assert search.select(chunks, [], budget_tokens=100) == []


def test_fallback_is_latest_job_plus_top_projects():
    chunks = _chunks()
    idx = search.fallback(large_profile(), chunks)
    titles = _titles(chunks, idx)
    assert "Engineer level 9 at Company9" in titles  # ongoing job = most recent
    assert sum(t.startswith("Project") for t in titles) == 3
