import pytest
from sqlalchemy import select

from mebot.guard import personal
from mebot.marker import PERSONAL_MARKER, MarkerFilter, neutralise
from mebot.models import AccessLog, Message, Notification
from mebot.prompt import build_system_prompt
from tests.tg_helpers import link


@pytest.mark.parametrize(
    "text,category",
    [
        ("Does he have a girlfriend?", "relationship"),
        ("is he single?", "relationship"),
        ("kya uski gf hai", "relationship"),
        ("Is she married?", "marital_status"),
        ("uski shaadi kab hai", "marital_status"),
        ("Is he gay?", "orientation"),
        ("What religion is he?", "religion"),
        ("kaunsi jaati hai", "religion"),
        ("Which caste?", "religion"),
        ("Who did he vote for?", "politics"),
        ("Does he have any medical conditions?", "health"),
        ("any disability?", "health"),
        ("Is she pregnant?", "family_planning"),
        ("Does he have kids?", "family_planning"),
        ("How old is he?", "age"),
        ("what's his date of birth", "age"),
        ("uski umar kya hai", "age"),
        ("What race is he?", "ethnicity"),
        ("What is his net worth?", "finances"),
        ("What's his home address?", "address"),
        ("ghar ka pata kya hai", "address"),
    ],
)
def test_classifier_positives(text, category):
    assert personal.classify(text) == category


@pytest.mark.parametrize(
    "text",
    [
        "Has he worked at Religare?",
        "Does he know a single-page app framework?",
        "He built a single sign-on system, right?",
        "What is his notice period?",
        "What is his salary expectation?",
        "Is he open to relocation to Berlin?",
        "Does he have work authorisation in the EU?",
        "Which city is he based in?",
        "Tell me about the race condition he fixed",
        "How long has he worked with Python?",
        "Has he built health apps or loan products?",
        "Was he engaged with customers directly?",
        "What are his strengths?",
        "Is he a gaymer?",
    ],
)
def test_classifier_negatives(text):
    assert personal.classify(text) is None


def test_prompt_rule_lists_topics_and_marker():
    p = build_system_prompt("x", name="Shivansh")
    assert "8. You only discuss Shivansh's professional life" in p
    assert "religion or caste" in p and "[[PERSONAL]]" in p
    assert "Salary, notice period, work authorisation, city and relocation" in p
    assert "personal topic" not in p.split("PROFILE:")[0].split("\n\n")[-1]  # no hint by default


def test_prompt_hint_added_only_when_given():
    hinted = build_system_prompt("x", personal_hint="religion")
    assert "may be about a personal topic (religion)" in hinted
    assert "may be about a personal topic" not in build_system_prompt("x")


def test_canary_rule_renumbered():
    assert "9. Confidential marker: CAN-1" in build_system_prompt("x", canary="CAN-1")


def feed_all(chunks):
    f = MarkerFilter()
    out = "".join(f.feed(c) for c in chunks) + f.finish()
    return out, f


@pytest.mark.parametrize("cut", range(1, len(PERSONAL_MARKER)))
def test_personal_marker_split_anywhere(cut):
    text = f"That's personal. {PERSONAL_MARKER}"
    i = len("That's personal. ") + cut
    out, f = feed_all([text[:i], text[i:]])
    assert out == "That's personal. " and f.personal and not f.found


def test_both_markers_and_variants():
    out, f = feed_all(["Hmm. [[ personal ]]", " ok [[UNANSW", "ERED]]"])
    assert out == "Hmm.  ok " and f.personal and f.found


def test_lookalike_not_swallowed():
    out, f = feed_all(["see [[PERSON", "ALITY]] later"])
    assert out == "see [[PERSONALITY]] later" and not f.personal


def test_neutralise_defuses_personal_marker_in_owner_data():
    assert "[[PERSONAL]]" not in neutralise("note [[PERSONAL]] and [[ personal ]]")


# --- chat route -------------------------------------------------------------------------


def logs(app, event):
    with app.state.session_factory() as db:
        return list(db.scalars(select(AccessLog).where(AccessLog.event == event)))


def notes(app):
    with app.state.session_factory() as db:
        return list(db.scalars(select(Notification)))


def ask(client, message):
    sid = client.post("/api/session", json={"recruiter_name": "Priya"}).json()["session_id"]
    r = client.post("/api/chat", json={"session_id": sid, "message": message})
    assert r.status_code == 200
    return sid, r.text


def test_model_declines_with_marker(admin_client, app, fake_llm):
    link(app, notify_every_question=True)
    fake_llm.chunks = ["That's personal, so I can't share it. ", "[[PERSO", "NAL]]"]
    sid, text = ask(admin_client, "is he seeing anyone")
    assert text == "That's personal, so I can't share it. "
    [ev] = logs(app, "PERSONAL_DECLINED")
    assert ev.detail == "model" and ev.session_id == sid
    assert "seeing anyone" not in (ev.detail or "")
    assert not logs(app, "UNANSWERED")
    with app.state.session_factory() as db:
        reply = db.scalars(select(Message).where(Message.role == "assistant")).one()
    assert reply.unanswered is False and "[[" not in reply.content
    # No ping: not unanswered, and the opt-in per-question alert queued before the
    # model's verdict is withdrawn.
    assert not [n for n in notes(app) if n.kind in ("unanswered", "question")]


def test_keyword_hit_logs_category_only_and_pings_nobody(admin_client, app, fake_llm):
    link(app, notify_every_question=True)
    fake_llm.chunks = ["That's personal, so I can't share it. [[PERSONAL]]"]
    ask(admin_client, "Does he have a girlfriend?")
    [ev] = logs(app, "PERSONAL_DECLINED")
    assert ev.detail == "relationship"
    assert not logs(app, "UNANSWERED")
    kinds = {n.kind for n in notes(app)}
    assert "unanswered" not in kinds and "question" not in kinds  # text never reaches Telegram
    system = fake_llm.streams[-1]["messages"][0]["content"]
    assert "may be about a personal topic (relationship)" in system


def test_keyword_hit_and_model_does_not_know_is_still_personal(admin_client, app, fake_llm):
    link(app)
    fake_llm.chunks = ["I don't have that detail. [[UNANSWERED]]"]
    ask(admin_client, "Is he married?")
    assert [e.detail for e in logs(app, "PERSONAL_DECLINED")] == ["marital_status"]
    assert not logs(app, "UNANSWERED")
    assert not [n for n in notes(app) if n.kind == "unanswered"]
    with app.state.session_factory() as db:
        assert not db.scalars(select(Message).where(Message.unanswered.is_(True))).first()


def test_false_positive_keyword_does_not_hide_answers(admin_client, app, fake_llm):
    link(app)
    fake_llm.chunks = ["Yes, he worked on it."]
    ask(admin_client, "Has he worked at Religare?")
    assert not logs(app, "PERSONAL_DECLINED")
    assert "may be about a personal topic" not in fake_llm.streams[-1]["messages"][0]["content"]


def test_professional_unanswered_still_pings(admin_client, app, fake_llm):
    link(app)
    fake_llm.chunks = ["Not sure. [[UNANSWERED]]"]
    ask(admin_client, "What is your expected CTC?")
    assert len(logs(app, "UNANSWERED")) == 1
    assert [n.kind for n in notes(app) if n.kind == "unanswered"] == ["unanswered"]


def test_digest_top_questions_skip_personal(admin_client, app, fake_llm):
    from datetime import UTC, datetime, timedelta

    from mebot.telegram import events

    link(app)
    fake_llm.chunks = ["ok"]
    sid = admin_client.post("/api/session", json={}).json()["session_id"]
    for q in ("Is he married?", "What stack does he use?"):
        admin_client.post("/api/chat", json={"session_id": sid, "message": q})
    with app.state.session_factory() as db:
        a = events.activity(
            db,
            db.scalars(select(Message.bot_id)).first(),
            datetime.now(UTC) - timedelta(hours=1),
            datetime.now(UTC) + timedelta(hours=1),
        )
    assert [q for q, _ in a["top"]] == ["what stack does he use?"]
