import json

from sqlalchemy import select

from mebot.llm.base import LLMError
from mebot.models import Message
from mebot.profile.sections import SECTIONS
from mebot.repos import bots
from mebot.repos import profile_items as items
from mebot.repos import retrieval as repo
from tests.retrieval_fixtures import large_profile
from tests.test_chat_limits import chat, new_session, set_limits


def seed_large_profile(app):
    p = large_profile()
    with app.state.session_factory() as db:
        bot_id = bots.get_primary(db).id
        for slug, rows in p.sections.items():
            for raw in rows:
                items.create(db, SECTIONS[slug], bot_id, SECTIONS[slug].schema.model_validate(raw))
        items.put_notes(db, bot_id, SECTIONS_NOTES(p.notes))
        db.commit()
    return bot_id


def SECTIONS_NOTES(content):
    from mebot.profile.schemas import NotesIn

    return NotesIn(content=content)


def system_prompt(fake_llm) -> str:
    return fake_llm.streams[-1]["messages"][0]["content"]


def assistant_messages(app):
    with app.state.session_factory() as db:
        return list(db.scalars(select(Message).where(Message.role == "assistant")))


def test_small_profile_chat_has_no_retrieval(admin_client, app, fake_llm):
    sid = new_session(admin_client)
    assert chat(admin_client, sid, "hello").status_code == 200
    prompt = system_prompt(fake_llm)
    assert "PROFILE OUTLINE" not in prompt and "PROFILE EXCERPTS" not in prompt
    assert "the PROFILE cannot answer it" in prompt
    assert assistant_messages(app)[0].chunk_ids is None


def test_large_profile_chat_sends_outline_and_only_relevant_excerpts(admin_client, app, fake_llm):
    seed_large_profile(app)
    sid = new_session(admin_client)
    r = chat(admin_client, sid, "Tell me about the Elasticsearch relevance work")
    assert r.status_code == 200 and r.text == "Hello there"
    prompt = system_prompt(fake_llm)
    assert "=== PROFILE OUTLINE" in prompt and "=== PROFILE EXCERPTS" in prompt
    assert "[PROJECTS] Project Elasticsearch 4" in prompt
    assert "Project Kafka 30" in prompt  # the outline still names it
    assert "[PROJECTS] Project Kafka 30" not in prompt  # but its details were not retrieved
    assert "the PROFILE excerpts and OUTLINE cannot answer it" in prompt
    assert "=== FACTS (computed by the system" in prompt
    # chunk ids stored on the reply, resolvable to titles
    msg = assistant_messages(app)[0]
    ids = json.loads(msg.chunk_ids)
    with app.state.session_factory() as db:
        titles = [t["title"] for t in repo.titles(db, msg.bot_id, msg.chunk_ids)]
    assert len(ids) == len(titles) >= 3
    assert any(t.startswith("Project Elasticsearch") for t in titles)


def test_follow_up_question_retrieves_using_previous_message(admin_client, app, fake_llm):
    seed_large_profile(app)
    sid = new_session(admin_client)
    chat(admin_client, sid, "Tell me about the Elasticsearch relevance project")
    chat(admin_client, sid, "what stack did it use?")
    assert "[PROJECTS] Project Elasticsearch 4" in system_prompt(fake_llm)


def test_unanswered_marker_still_works_in_retrieval_mode(admin_client, app, fake_llm):
    seed_large_profile(app)
    fake_llm.chunks = ["I don't have that detail yet. [[UNANSWERED]]"]
    sid = new_session(admin_client)
    r = chat(admin_client, sid, "What is the airspeed of a swallow?")
    assert "[[" not in r.text
    assert assistant_messages(app)[0].unanswered is True


def test_mode_off_override_sends_the_whole_profile(admin_client, app, fake_llm):
    bot_id = seed_large_profile(app)
    with app.state.session_factory() as db:
        row = repo.get_or_create_settings(db, bot_id)
        row.mode = "off"
        db.commit()
    sid = new_session(admin_client)
    chat(admin_client, sid, "hi")
    prompt = system_prompt(fake_llm)
    assert "PROFILE EXCERPTS" not in prompt and "[PROJECTS]" not in prompt
    assert "- Project Kafka 30" in prompt  # the full projects block


def test_query_embedding_failure_never_breaks_chat(admin_client, app, fake_llm):
    bot_id = seed_large_profile(app)
    with app.state.session_factory() as db:
        row = repo.get_or_create_settings(db, bot_id)
        row.embeddings_enabled, row.embedding_model = True, "emb"
        db.commit()
    fake_llm.embed_fail = LLMError("provider", "down", 500)
    set_limits(app, per_ip_per_minute=100)
    sid = new_session(admin_client)
    r = chat(admin_client, sid, "Elasticsearch relevance")
    assert r.status_code == 200 and r.text == "Hello there"
    assert "[PROJECTS] Project Elasticsearch 4" in system_prompt(fake_llm)
