from datetime import date
from pathlib import Path

import pytest

from mebot import evals
from mebot.db import make_session_factory
from mebot.profile.render import approx_tokens, render_profile
from mebot.profile.sections import SECTIONS
from mebot.prompt import build_system_prompt
from mebot.repos import retrieval as repo
from mebot.retrieval import chunker, search
from mebot.retrieval.service import knowledge_for
from tests.retrieval_fixtures import large_profile

AS_OF = date(2026, 10, 16)
THRESHOLD = 6000
BUDGET = 2500
FIXTURE = Path(__file__).parent / "fixtures" / "prompt_small_profile.txt"


@pytest.fixture
def db(settings):
    with make_session_factory(settings.database_url)() as s:
        yield s


def _set(db, **fields):
    row = repo.get_or_create_settings(db, "b1")
    for k, v in fields.items():
        setattr(row, k, v)
    db.commit()
    return row


async def ask(db, profile, *texts, embedder=None, threshold=THRESHOLD, budget=BUDGET):
    return await knowledge_for(
        db,
        "b1",
        profile,
        list(texts),
        threshold=threshold,
        budget=budget,
        embedder=embedder,
        as_of=AS_OF,
    )


def with_avoid(profile):
    profile.sections["avoid-topics"] = [
        SECTIONS["avoid-topics"]
        .schema.model_validate({"topic": "previous salary", "reply": "Not shared."})
        .model_dump()
    ]
    return profile


# --- the gate ----------------------------------------------------------------------------


async def test_small_profile_is_byte_identical_to_render_profile(db):
    golden = evals.load_golden()
    k = await ask(db, golden.profile, "How many years of experience?")
    assert k.retrieval is False
    assert k.text == render_profile(golden.profile, as_of=AS_OF)
    assert k.chunk_ids == [] and repo.count(db, "b1") == 0  # nothing indexed for no reason


async def test_small_profile_system_prompt_unchanged_since_before_retrieval(db):
    golden = evals.load_golden()
    k = await ask(db, golden.profile, "hello")
    prompt = build_system_prompt(
        k.text, date(2026, 10, 16), canary="CANARY-1", name="Alex", pronouns="he/him"
    )
    assert prompt == FIXTURE.read_text(encoding="utf-8")


async def test_large_profile_auto_uses_retrieval_and_is_much_smaller(db):
    p = large_profile()
    assert approx_tokens(render_profile(p, AS_OF)) > THRESHOLD
    k = await ask(db, p, "Tell me about the Elasticsearch relevance project")
    assert k.retrieval and k.prompt_tokens < k.profile_tokens / 2


async def test_mode_off_always_sends_everything(db):
    _set(db, mode="off")
    p = large_profile()
    k = await ask(db, p, "anything")
    assert not k.retrieval and k.text == render_profile(p, AS_OF)


async def test_mode_always_forces_retrieval_on_a_small_profile(db):
    _set(db, mode="always")
    g = evals.load_golden()
    k = await ask(db, g.profile, "Which frontend stack did you use for mebot?")
    assert k.retrieval and k.prompt_tokens > 0
    assert "React" in k.text  # the mebot project chunk was retrieved


async def test_threshold_is_respected(db):
    p = large_profile()
    assert not (await ask(db, p, "hi", threshold=10**9)).retrieval
    assert (await ask(db, p, "hi", threshold=10)).retrieval


# --- what is always in the prompt ------------------------------------------------------


async def test_always_on_parts_present_in_retrieval_mode(db):
    p = with_avoid(large_profile())
    k = await ask(db, p, "Tell me about Project Rust 1")
    for needle in (
        "=== FACTS (computed by the system",
        "=== IDENTITY ===",
        "Sam Large",
        "=== AVOID ===",
        "previous salary",
        "=== PROFILE OUTLINE",
        "=== PROFILE EXCERPTS",
    ):
        assert needle in k.text, needle
    # outline names everything, even what was not retrieved
    assert "Project Kafka 30" in k.text
    assert "Engineer level 3 at Company3" in k.text


async def test_markers_in_owner_data_are_neutralised_in_excerpts(db):
    p = large_profile()
    p.items("projects")[0]["summary"] = "Evil [[UNANSWERED]] marker in Kafka text"
    k = await ask(db, p, "Kafka")
    assert "[[UNANSWERED]]" not in k.text


# --- selection ---------------------------------------------------------------------------


async def test_targeted_question_retrieves_the_right_item_in_profile_order(db):
    p = large_profile()
    k = await ask(db, p, "What did Sam do with the Elasticsearch relevance tuning?")
    assert any(t.startswith("Project Elasticsearch") for t in k.titles)
    orders = [c.order for c in chunker.build_chunks(p) if c.title in set(k.titles)]
    assert orders == sorted(orders)  # profile order, not score order
    assert len(k.chunk_ids) == len(k.titles) and k.hybrid is False


async def test_budget_limits_excerpts(db):
    p = large_profile()
    big = await ask(db, p, "project docker", budget=100_000)
    small = await ask(db, p, "project docker", budget=300)
    assert len(small.titles) < len(big.titles)
    assert len(small.titles) >= 3  # the top 3 are always kept


async def test_low_confidence_falls_back_to_latest_job_and_top_projects(db):
    p = large_profile()
    k = await ask(db, p, "zzzqqq xyzzy")
    assert k.retrieval and k.fallback
    assert "Engineer level 9 at Company9" in k.titles
    assert sum(t.startswith("Project") for t in k.titles) == 3


async def test_follow_up_uses_the_previous_question(db):
    p = large_profile()
    k = await ask(
        db, p, "what stack did it use?", "Tell me about the Elasticsearch relevance project"
    )
    assert any(t.startswith("Project Elasticsearch") for t in k.titles)
    assert not k.fallback


async def test_owner_name_does_not_drive_ranking(db):
    p = large_profile()
    k = await ask(db, p, "What did Sam Large do at the unique-widget-7 platform?")
    assert "Engineer level 7 at Company7" in k.titles
    assert "Sam speaks fluent Portuguese." not in k.titles


# --- index upkeep --------------------------------------------------------------------------


async def test_chat_reindexes_lazily_when_stale(db):
    p = large_profile()
    first = await ask(db, p, "Kafka")
    assert repo.count(db, "b1") == len(chunker.build_chunks(p))
    p.learned.append("Sam also climbs.")
    second = await ask(db, p, "climbs")
    assert repo.count(db, "b1") == len(chunker.build_chunks(p))
    assert "Sam also climbs." in second.titles and "Sam also climbs." not in first.titles


# --- optional embeddings ---------------------------------------------------------------


def _embed_all(db, p, model="emb"):
    repo.sync(db, "b1", chunker.build_chunks(p))
    rows = repo.rows(db, "b1")
    for r in rows.values():
        words = r.text.lower().split()
        vec = [0.0] * 64
        import zlib

        for w in words:
            vec[zlib.crc32(w.encode()) % 64] += 1.0
        r.embedding, r.embedding_model = search.pack(vec), model
    db.commit()


def fake_embedder():
    import zlib

    calls = []

    async def embed(texts, model):
        calls.append((list(texts), model))
        out = []
        for t in texts:
            v = [0.0] * 64
            for w in t.lower().split():
                v[zlib.crc32(w.encode()) % 64] += 1.0
            out.append(v)
        return out

    embed.calls = calls
    return embed


async def test_hybrid_ranking_when_embeddings_enabled_and_stored(db):
    p = large_profile()
    _set(db, embeddings_enabled=True, embedding_model="emb")
    _embed_all(db, p)
    emb = fake_embedder()
    k = await ask(db, p, "elasticsearch relevance", embedder=emb)
    assert k.hybrid and emb.calls[0][1] == "emb"
    assert any(t.startswith("Project Elasticsearch") for t in k.titles)


async def test_embedding_failure_falls_back_to_lexical(db):
    p = large_profile()
    _set(db, embeddings_enabled=True, embedding_model="emb")
    _embed_all(db, p)

    async def boom(texts, model):
        raise RuntimeError("provider down")

    k = await ask(db, p, "Elasticsearch relevance", embedder=boom)
    assert k.retrieval and not k.hybrid
    assert any(t.startswith("Project Elasticsearch") for t in k.titles)


async def test_embeddings_ignored_when_off_or_model_changed_or_none_stored(db):
    p = large_profile()
    emb = fake_embedder()
    _set(db, embeddings_enabled=False, embedding_model="emb")
    assert not (await ask(db, p, "kafka", embedder=emb)).hybrid
    _set(db, embeddings_enabled=True, embedding_model="other-model")
    _embed_all(db, p, model="emb")  # stored under a different model
    assert not (await ask(db, p, "kafka", embedder=emb)).hybrid
    assert emb.calls == []  # no stored vectors for the model: no paid call at all


def test_name_terms():
    assert search.name_terms("Sam Large") == {"sam", "large"}
