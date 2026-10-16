from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from mebot.models import AccessLog, Notification, OpenQuestion
from mebot.repos import bots
from mebot.repos import open_questions as oq
from tests.test_chat_limits import chat
from tests.tg_helpers import link

T0 = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)


def test_normalize_drops_stopwords_and_punctuation():
    assert oq.normalize("Where do you live?") == "live"
    assert oq.normalize("Where does he LIVE!!") == "live"
    assert oq.normalize("What's the notice-period?") == "notice period"
    assert oq.normalize("???") == ""


@pytest.mark.parametrize(
    "a,b,expected",
    [
        ("where are you based", "where do you live", False),  # different tokens: separate
        ("what is his notice period", "notice period?", True),
        ("do you have a driving licence", "driving licence?", True),
        ("kya aap relocate karenge", "will he relocate", False),
    ],
)
def test_grouping_by_jaccard(a, b, expected):
    assert (oq.similarity(oq.normalize(a), oq.normalize(b)) >= oq.SIMILARITY) is expected


def test_similarity_threshold_boundary():
    # 3 shared of 5 total tokens = exactly 0.6 -> grouped; 2 of 6 -> separate.
    assert oq.similarity("a b c d", "a b c e") == 0.6
    assert oq.similarity("a b c d", "a b e f") == pytest.approx(1 / 3)
    assert oq.similarity("", "a") == 0.0 and oq.similarity("", "") == 0.0


def _bot(db):
    return bots.get_primary(db).id


def test_record_counts_rephrasings(admin_client, app):
    with app.state.session_factory() as db:
        bot_id = _bot(db)
        first, new1 = oq.record(db, bot_id, "What is his notice period?", "s1", T0)
        second, new2 = oq.record(db, bot_id, "notice period??", "s2", T0 + timedelta(hours=1))
        other, new3 = oq.record(db, bot_id, "Does he have a driving licence?", "s3", T0)
        db.commit()
        assert new1 and not new2 and new3
        assert second.id == first.id and first.ask_count == 2
        assert first.question == "What is his notice period?"  # first-seen wording
        assert first.last_session_id == "s2"
        assert first.last_asked_at == T0 + timedelta(hours=1) and first.first_asked_at == T0
        assert other.id != first.id


def test_all_stopword_question_groups_only_on_exact_repeat(admin_client, app):
    with app.state.session_factory() as db:
        bot_id = _bot(db)
        a, _ = oq.record(db, bot_id, "Are you?", "s", T0)
        b, new_b = oq.record(db, bot_id, "are you", "s", T0)
        c, new_c = oq.record(db, bot_id, "Do you?", "s", T0)
        assert a.id == b.id and not new_b and c.id != a.id and new_c


def test_only_open_groups_match_and_bots_are_isolated(admin_client, app):
    with app.state.session_factory() as db:
        bot_id = _bot(db)
        a, _ = oq.record(db, bot_id, "notice period", "s", T0)
        oq.set_status(db, a, "dismissed")
        b, new_b = oq.record(db, bot_id, "notice period", "s", T0)
        assert new_b and b.id != a.id
        other, new_o = oq.record(db, "other-bot", "notice period", "s", T0)
        assert new_o and other.ask_count == 1


def test_should_notify_first_then_every_24h():
    row = OpenQuestion(bot_id="b", question="q", normalized="q", last_notified_at=None)
    assert oq.should_notify(row, T0)
    row.last_notified_at = T0
    assert not oq.should_notify(row, T0 + timedelta(hours=23, minutes=59))
    assert oq.should_notify(row, T0 + timedelta(hours=24))


def test_list_sorted_by_count_then_recency(admin_client, app):
    with app.state.session_factory() as db:
        bot_id = _bot(db)
        oq.record(db, bot_id, "alpha topic", "s", T0)
        oq.record(db, bot_id, "beta topic", "s", T0 + timedelta(hours=1))
        oq.record(db, bot_id, "gamma topic", "s", T0)
        oq.record(db, bot_id, "gamma topic", "s", T0 + timedelta(hours=2))
        db.commit()
        assert [r.question for r in oq.list_(db, bot_id)] == [
            "gamma topic",
            "beta topic",
            "alpha topic",
        ]
        assert oq.count_open(db, bot_id) == 3


# --- chat + telegram ping dedup -----------------------------------------------------


def pings(app):
    with app.state.session_factory() as db:
        return list(db.scalars(select(Notification).where(Notification.kind == "unanswered")))


def test_chat_records_group_and_throttles_pings(admin_client, app, fake_llm):
    link(app)
    fake_llm.chunks = ["No idea. [[UNANSWERED]]"]
    sid = admin_client.post("/api/session", json={"recruiter_name": "Priya"}).json()["session_id"]
    chat(admin_client, sid, "What is his notice period?")
    chat(admin_client, sid, "notice period?")
    chat(admin_client, sid, "what's the notice period")
    with app.state.session_factory() as db:
        [group] = list(db.scalars(select(OpenQuestion)))
        assert group.ask_count == 3 and group.status == "open"
        assert len(list(db.scalars(select(AccessLog).where(AccessLog.event == "UNANSWERED")))) == 3
    [first] = pings(app)  # only the first ask pinged
    assert "asked" not in first.payload
    assert group.id in first.payload


def test_ping_again_after_24h_with_count(admin_client, app, fake_llm):
    link(app)
    fake_llm.chunks = ["No idea. [[UNANSWERED]]"]
    sid = admin_client.post("/api/session", json={}).json()["session_id"]
    chat(admin_client, sid, "notice period?")
    chat(admin_client, sid, "notice period?")
    with app.state.session_factory() as db:
        g = db.scalars(select(OpenQuestion)).one()
        g.last_notified_at = datetime.now(UTC) - timedelta(hours=25)
        db.commit()
    chat(admin_client, sid, "notice period?")
    notes = pings(app)
    assert len(notes) == 2
    assert "(asked 3×)" in notes[-1].payload


def test_personal_question_creates_no_group(admin_client, app, fake_llm):
    link(app)
    fake_llm.chunks = ["Personal. [[PERSONAL]]"]
    sid = admin_client.post("/api/session", json={}).json()["session_id"]
    chat(admin_client, sid, "Is he married?")
    with app.state.session_factory() as db:
        assert not db.scalars(select(OpenQuestion)).first()
