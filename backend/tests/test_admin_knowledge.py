import json

from sqlalchemy import select

from mebot.llm.base import LLMError
from mebot.models import LLMConfig, UsageCounter
from mebot.repos import bots
from mebot.repos import retrieval as repo
from mebot.retrieval import index
from tests.conftest import csrf, do_setup
from tests.test_admin_learning import cleaned
from tests.test_chat_limits import chat, new_session, set_limits
from tests.test_retrieval_chat import seed_large_profile

K = "/api/admin/knowledge"


def put(c, body):
    return c.put(K, json=body, headers=csrf(c))


def primary_id(app):
    with app.state.session_factory() as db:
        return bots.get_primary(db).id


def chunk_rows(app, bot_id):
    with app.state.session_factory() as db:
        return repo.rows(db, bot_id)


def set_provider(app, provider):
    with app.state.session_factory() as db:
        row = db.scalar(select(LLMConfig))
        row.provider = provider
        db.commit()


def test_requires_admin(client):
    do_setup(client)
    client.cookies.clear()
    assert client.get(K).status_code == 401
    assert client.put(K, json={"mode": "off"}).status_code in (401, 403)


def test_status_small_profile_uses_full_mode(admin_client):
    body = admin_client.get(K).json()
    assert body["mode"] == "auto" and body["effective"] == "full"
    assert body["threshold_tokens"] == 6000 and body["budget_tokens"] == 2500
    assert 0 <= body["profile_tokens"] < 6000
    assert "within" in body["reason"]
    assert body["chunk_count"] == 0 and body["last_indexed_at"] is None
    emb = body["embeddings"]
    assert emb["supported"] is True and emb["enabled"] is False
    assert emb["default_model"] == "text-embedding-3-small"


def test_status_large_profile_uses_retrieval(admin_client, app):
    seed_large_profile(app)
    body = admin_client.get(K).json()
    assert body["effective"] == "retrieval" and body["profile_tokens"] > 6000
    assert "above" in body["reason"]
    assert body["index_stale"] is True  # nothing indexed yet (no save hook ran: seeded directly)


def test_profile_save_reindexes_in_background(admin_client, app):
    bot_id = seed_large_profile(app)
    r = admin_client.post(
        "/api/admin/profile/faqs",
        json={"question": "Favourite editor?", "answer": "Neovim"},
        headers=csrf(admin_client),
    )
    assert r.status_code == 201
    rows = chunk_rows(app, bot_id)
    assert "faqs:" + r.json()["id"] in rows and len(rows) > 50
    assert admin_client.get(K).json()["index_stale"] is False
    # deleting removes the chunk
    admin_client.delete(f"/api/admin/profile/faqs/{r.json()['id']}", headers=csrf(admin_client))
    assert "faqs:" + r.json()["id"] not in chunk_rows(app, bot_id)


def test_put_mode_validates_and_applies(admin_client):
    assert put(admin_client, {"mode": "always"}).json()["effective"] == "retrieval"
    assert "forced on" in admin_client.get(K).json()["reason"].lower()
    assert put(admin_client, {"mode": "off"}).json()["effective"] == "full"
    assert put(admin_client, {"mode": "bogus"}).status_code == 422
    assert put(admin_client, {"mode": "auto"}).json()["mode"] == "auto"


def test_embeddings_unsupported_provider_is_rejected_with_explanation(admin_client, app):
    set_provider(app, "anthropic")
    status = admin_client.get(K).json()["embeddings"]
    assert status["supported"] is False and "Anthropic" in status["reason"]
    r = put(admin_client, {"embeddings_enabled": True})
    assert r.status_code == 422 and "Anthropic" in r.json()["error"]["message"]


def test_enable_embeddings_embeds_chunks_and_counts_tokens(admin_client, app, fake_llm):
    bot_id = seed_large_profile(app)
    r = put(admin_client, {"embeddings_enabled": True})
    assert r.status_code == 200, r.text
    emb = r.json()["embeddings"]
    assert emb["enabled"] is True and emb["model"] == "text-embedding-3-small"
    rows = chunk_rows(app, bot_id)
    assert rows and all(x.embedding and x.embedding_model == emb["model"] for x in rows.values())
    assert fake_llm.embed_calls  # batched: far fewer calls than chunks
    assert len(fake_llm.embed_calls) < len(rows)
    assert admin_client.get(K).json()["embeddings"]["embedded"] == len(rows)
    with app.state.session_factory() as db:
        counter = db.scalar(
            select(UsageCounter).where(UsageCounter.scope == "bot_day", UsageCounter.tokens > 0)
        )
    assert counter is not None and counter.estimated_tokens > 0


def test_embedding_failure_is_recorded_and_lexical_still_works(admin_client, app, fake_llm):
    seed_large_profile(app)
    fake_llm.embed_fail = LLMError("auth", "OpenAI rejected the API key (401)", 401)
    assert put(admin_client, {"embeddings_enabled": True}).status_code == 200
    emb = admin_client.get(K).json()["embeddings"]
    assert emb["embedded"] == 0 and "rejected the API key" in emb["last_error"]
    set_limits(app, per_ip_per_minute=100)
    sid = new_session(admin_client)
    r = chat(admin_client, sid, "Elasticsearch relevance")
    assert r.status_code == 200
    assert "[PROJECTS] Project Elasticsearch 4" in fake_llm.streams[-1]["messages"][0]["content"]


def test_embeddings_respect_the_daily_token_cap(admin_client, app, fake_llm, monkeypatch):
    monkeypatch.setattr(index, "EMBED_BATCH", 20)
    seed_large_profile(app)
    set_limits(app, daily_token_cap=1)
    # cap not yet reached: first batch goes through, then the cap stops further batches
    put(admin_client, {"embeddings_enabled": True})
    assert len(fake_llm.embed_calls) == 1
    assert "token cap" in admin_client.get(K).json()["embeddings"]["last_error"]


def test_small_profile_never_pays_for_embeddings(admin_client, fake_llm):
    assert put(admin_client, {"embeddings_enabled": True}).status_code == 200
    assert fake_llm.embed_calls == []


def test_rebuild_rechunks_and_reembeds(admin_client, app, fake_llm):
    bot_id = seed_large_profile(app)
    put(admin_client, {"embeddings_enabled": True})
    calls = len(fake_llm.embed_calls)
    r = admin_client.post(f"{K}/rebuild", headers=csrf(admin_client))
    assert r.status_code == 200 and r.json()["index_stale"] is False
    assert len(fake_llm.embed_calls) > calls  # vectors were recomputed
    assert all(x.embedding for x in chunk_rows(app, bot_id).values())


def test_learned_fact_approval_triggers_reindex(admin_client, app, fake_llm):
    bot_id = primary_id(app)
    put(admin_client, {"mode": "always"})
    cleaned(fake_llm, fact_text="Shivansh speaks fluent Hindi.")
    r = admin_client.post(
        "/api/admin/learned-facts",
        json={"text": "Shivansh speaks fluent Hindi."},
        headers=csrf(admin_client),
    )
    assert r.status_code == 201, r.text
    fid = r.json()["id"]
    admin_client.post(
        f"/api/admin/learned-facts/{fid}/approve", json={}, headers=csrf(admin_client)
    )
    titles = [x.title for x in chunk_rows(app, bot_id).values()]
    assert any("Hindi" in t for t in titles)


def test_conversation_detail_lists_retrieved_chunks(admin_client, app, fake_llm):
    seed_large_profile(app)
    sid = new_session(admin_client)
    chat(admin_client, sid, "Tell me about the Elasticsearch relevance project")
    detail = admin_client.get(f"/api/admin/conversations/{sid}").json()
    user, bot_msg = detail["messages"]
    assert "chunks" not in user
    titles = [c["title"] for c in bot_msg["chunks"]]
    assert any(t.startswith("Project Elasticsearch") for t in titles)
    assert set(bot_msg["chunks"][0]) == {"id", "section", "title"}


def test_conversation_detail_without_retrieval_has_no_chunks_key(admin_client, fake_llm):
    sid = new_session(admin_client)
    chat(admin_client, sid, "hi")
    msgs = admin_client.get(f"/api/admin/conversations/{sid}").json()["messages"]
    assert all("chunks" not in m for m in msgs)
    assert json.dumps(msgs)  # serialisable
