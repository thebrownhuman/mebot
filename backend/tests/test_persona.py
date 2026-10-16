import pytest

from mebot import evals, persona
from mebot.profile.data import ProfileData
from mebot.profile.render import render_facts, render_profile
from mebot.prompt import build_system_prompt
from tests.conftest import csrf
from tests.test_render_grounding import AS_OF, sample


def test_pronoun_forms():
    assert persona.pronouns_for("he/him").possessive == "his"
    assert persona.pronouns_for("she/her").subject == "she"
    assert persona.pronouns_for("they/them").possessive == "their"
    assert persona.pronouns_for("nonsense") == persona.pronouns_for("they/them")
    assert persona.pronouns_for(None) == persona.pronouns_for("they/them")


@pytest.mark.parametrize(
    "pronouns,expect,absent",
    [
        ("he/him", '"he", "him" or "his"', "Do not guess a gender"),
        ("she/her", '"she", "her" or "her"', "Do not guess a gender"),
        ("they/them", '"they" and "their". Do not guess a gender', '"he"'),
    ],
)
def test_prompt_is_third_person_for_each_pronoun(pronouns, expect, absent):
    prompt = build_system_prompt("x", name="Shivansh", pronouns=pronouns)
    assert "You are Shivansh's AI assistant" in prompt
    assert "third person" in prompt
    assert "Never speak as Shivansh" in prompt
    assert expect in prompt
    assert absent not in prompt
    assert "Speak in the first person" not in prompt
    assert "noted it for Shivansh" in prompt  # rule 3: the owner is told, not the visitor
    assert "you are an AI assistant answering on Shivansh's behalf" in prompt


def test_prompt_defaults_to_the_candidate_and_they():
    prompt = build_system_prompt("x")
    assert "You are the candidate's AI assistant" in prompt
    assert '"they" and "their"' in prompt


def test_facts_use_the_first_name_in_third_person():
    p = sample()
    p.identity["full_name"] = "Jane Doe"
    text = render_facts(p, AS_OF)
    assert "Jane's total professional experience" in text
    assert "Jane's current role" in text
    assert " I " not in text and "my " not in text.lower()
    assert "stated by owner" not in text


def test_identity_block_lists_pronouns():
    p = ProfileData(identity={"full_name": "Jane Doe", "pronouns": "she/her"})
    assert "Pronouns: she/her" in render_profile(p, as_of=AS_OF)


def test_greeting_default_and_custom():
    ident = {"full_name": "Shivansh Mishra", "pronouns": "he/him"}
    assert persona.render_greeting(ident) == (
        "Hi! I'm Shivansh's assistant. Ask me anything about his work, experience or projects."
    )
    ident["pronouns"] = "they/them"
    assert "about their work" in persona.render_greeting(ident)
    ident["assistant_greeting"] = "Hello, I help with {name}'s CV. {pronoun_subj} codes. {nope}"
    assert persona.render_greeting(ident) == (
        "Hello, I help with Shivansh Mishra's CV. they codes. {nope}"
    )


def test_greeting_survives_broken_template_and_missing_name():
    assert persona.render_greeting({"assistant_greeting": "oops {"}, "Zed Q").startswith(
        "Hi! I'm Zed's assistant"
    )
    assert persona.render_greeting({}, None).startswith("Hi! I'm the owner's assistant")


def test_golden_profile_third_person():
    golden = evals.load_golden()
    assert golden.profile.identity["pronouns"] == "he/him"
    assert golden.profile.items("avoid-topics")[0]["reply"].startswith("Alex ")


def test_identity_api_accepts_pronouns_and_greeting(admin_client):
    h = csrf(admin_client)
    r = admin_client.put(
        "/api/admin/profile/identity",
        json={
            "full_name": "Jane Doe",
            "pronouns": "she/her",
            "assistant_greeting": "Hi {first_name}",
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["pronouns"] == "she/her"
    assert admin_client.get("/api/public/config").json()["assistant_greeting"] == "Hi Jane"
    bad = admin_client.put("/api/admin/profile/identity", json={"pronouns": "xe/xem"}, headers=h)
    assert bad.status_code == 422


def test_public_config_default_greeting(admin_client):
    assert admin_client.get("/api/public/config").json()["assistant_greeting"] == (
        "Hi! I'm Shivansh's assistant. Ask me anything about their work, experience or projects."
    )


def test_chat_prompt_uses_owner_name_and_pronouns(admin_client, fake_llm):
    h = csrf(admin_client)
    admin_client.put(
        "/api/admin/profile/identity",
        json={"full_name": "Jane Doe", "pronouns": "she/her"},
        headers=h,
    )
    sid = admin_client.post("/api/session", json={}).json()["session_id"]
    admin_client.post("/api/chat", json={"session_id": sid, "message": "hi"}, headers=h)
    system = fake_llm.streams[-1]["messages"][0]["content"]
    assert "You are Jane's AI assistant" in system
    assert '"she", "her" or "her"' in system
