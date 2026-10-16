from mebot.models import ProfileIdentity
from mebot.repos import bots, profile_items
from tests.test_chat_limits import chat


def test_public_config_owner_name_falls_back_to_bot_name(admin_client):
    assert admin_client.get("/api/public/config").json()["owner_name"] == "Shivansh"


def test_public_config_owner_name_from_identity(admin_client, app):
    with app.state.session_factory() as db:
        bot = bots.get_primary(db)
        ident = profile_items.get_identity(db, bot.id) or ProfileIdentity(bot_id=bot.id)
        ident.full_name = "Shivansh Mishra"
        db.add(ident)
        db.commit()
    assert admin_client.get("/api/public/config").json()["owner_name"] == "Shivansh Mishra"


def test_updates_reports_unanswered_last_reply(admin_client, fake_llm):
    sid = admin_client.post("/api/session", json={}).json()["session_id"]
    assert admin_client.get(f"/api/session/{sid}/updates").json()["unanswered"] is False
    fake_llm.chunks = ["Not sure. [[UNANSWERED]]"]
    chat(admin_client, sid, "Expected CTC?")
    assert admin_client.get(f"/api/session/{sid}/updates").json()["unanswered"] is True
    fake_llm.chunks = ["Python, mostly."]
    chat(admin_client, sid, "Main language?")
    assert admin_client.get(f"/api/session/{sid}/updates").json()["unanswered"] is False
