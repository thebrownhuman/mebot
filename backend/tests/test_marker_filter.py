import pytest
from sqlalchemy import select

from mebot.marker import MarkerFilter
from mebot.models import AccessLog, Message


def run(chunks: list[str]) -> tuple[str, bool, list[str]]:
    f = MarkerFilter()
    shown = [f.feed(c) for c in chunks]
    shown.append(f.finish())
    return "".join(shown), f.found, shown


TEXT = "I don't have that detail. [[UNANSWERED]]"


def test_absent_passes_through():
    out, found, _ = run(["Hello ", "there [x] and [[link]]"])
    assert out == "Hello there [x] and [[link]]" and not found


def test_whole_marker_stripped():
    out, found, _ = run([TEXT])
    assert out == "I don't have that detail. " and found


@pytest.mark.parametrize("cut", range(1, len(TEXT)))
def test_split_at_every_position(cut):
    out, found, pieces = run([TEXT[:cut], TEXT[cut:]])
    assert out == "I don't have that detail. " and found
    assert not any("[[" in p or "UNANS" in p.upper() for p in pieces)


def test_one_char_chunks():
    out, found, pieces = run(list(TEXT))
    assert out == "I don't have that detail. " and found
    assert "".join(pieces) == out


@pytest.mark.parametrize("marker", ["[[unanswered]]", "[[ UNANSWERED ]]", "[[Unanswered ]]"])
def test_variants(marker):
    out, found, _ = run(["No idea. ", marker])
    assert out == "No idea. " and found


def test_mid_text_and_multiple():
    out, found, _ = run(["a [[UNANSWERED]] b ", "[[unans", "wered]] c"])
    assert out == "a  b  c" and found


def test_unfinished_lookalike_flushed_at_end():
    out, found, _ = run(["costs [[UNANSW"])
    assert out == "costs [[UNANSW" and not found


def test_text_is_not_held_longer_than_needed():
    f = MarkerFilter()
    assert f.feed("Hello world") == "Hello world"
    assert f.feed(" more [") == " more "
    assert f.feed("x") == "[x"


# --- chat route -------------------------------------------------------------------------


def test_chat_strips_marker_logs_and_flags(admin_client, app, fake_llm):
    fake_llm.chunks = ["I don't have my salary ", "details here. [[UNAN", "SWERED]]"]
    sid = admin_client.post("/api/session", json={}).json()["session_id"]
    q = "What is your expected CTC?" + " x" * 400
    r = admin_client.post("/api/chat", json={"session_id": sid, "message": q})
    assert r.status_code == 200
    assert "UNANSWERED" not in r.text.upper() and "[[" not in r.text
    assert r.text.startswith("I don't have my salary details here.")
    with app.state.session_factory() as db:
        msgs = list(
            db.scalars(
                select(Message).where(Message.session_id == sid).order_by(Message.created_at)
            )
        )
        logs = list(db.scalars(select(AccessLog).where(AccessLog.event == "UNANSWERED")))
    assert msgs[-1].role == "assistant" and msgs[-1].unanswered is True
    assert msgs[-1].content == "I don't have my salary details here."
    assert msgs[0].unanswered is False
    assert len(logs) == 1 and logs[0].session_id == sid
    assert logs[0].detail == q[:500]


def test_chat_answered_not_flagged(admin_client, app, fake_llm):
    sid = admin_client.post("/api/session", json={}).json()["session_id"]
    admin_client.post("/api/chat", json={"session_id": sid, "message": "hi"})
    with app.state.session_factory() as db:
        assert not db.scalars(select(Message).where(Message.unanswered.is_(True))).first()
        assert not db.scalars(select(AccessLog).where(AccessLog.event == "UNANSWERED")).first()
