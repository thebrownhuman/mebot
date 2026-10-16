import json

import pytest
from sqlalchemy import select

from mebot.errors import ApiError
from mebot.learning import service as svc
from mebot.models import AccessLog, LearnedFact, OpenQuestion
from mebot.profile.data import ProfileData, load_profile
from mebot.profile.render import render_profile
from mebot.repos import bots, learned_facts, open_questions
from mebot.repos import profile_items as profile
from tests.conftest import csrf


def reply(fake_llm, **over):
    out = {
        "fact_text": "Shivansh lives in Bangalore and is open to remote work.",
        "section": "learned",
        "field": None,
        "value": None,
        "personal_only": False,
    }
    out.update(over)
    fake_llm.chunks = [json.dumps(out)]


@pytest.fixture
def ctx(admin_client, app):
    """(db, bot_id, secret_key) for direct service calls."""
    with app.state.session_factory() as db:
        yield db, bots.get_primary(db).id, app.state.secret_key


async def propose(ctx, fake_llm, answer="Bangalore, open to remote", oq_id=None, **over):
    db, bot_id, secret = ctx
    reply(fake_llm, **over)
    fact = await svc.propose(
        db, bot_id, secret, question="Where does he live?", answer=answer, source="admin",
        open_question_id=oq_id,
    )  # fmt: skip
    db.commit()
    return fact


def set_identity(ctx, **values):
    db, bot_id, _ = ctx
    from mebot.profile.schemas import IdentityIn

    profile.put_identity(db, bot_id, IdentityIn(full_name="Shivansh Mishra", **values))
    db.commit()


def make_question(ctx, text="Where does he live?"):
    db, bot_id, _ = ctx
    q, _ = open_questions.record(db, bot_id, text, "s1")
    db.commit()
    return q


# --- propose ---------------------------------------------------------------------------


async def test_propose_creates_pending_fact_unknown_to_the_bot(ctx, fake_llm):
    fact = await propose(ctx, fake_llm)
    assert fact.status == "pending" and fact.source == "admin"
    assert fact.fact_text.startswith("Shivansh lives in Bangalore")
    assert fact.answer_raw == "Bangalore, open to remote"
    db, bot_id, _ = ctx
    assert load_profile(db, bot_id).learned == []  # not approved: the bot doesn't know it


async def test_propose_sends_owner_name_and_pronouns_to_the_llm(ctx, fake_llm):
    set_identity(ctx, pronouns="she/her")
    await propose(ctx, fake_llm)
    user = json.loads(fake_llm.streams[-1]["messages"][1]["content"])
    assert user["owner_name"] == "Shivansh" and user["pronouns"] == "she/her"


async def test_propose_personal_answer_is_rejected_and_not_stored(ctx, fake_llm):
    with pytest.raises(ApiError) as e:
        await propose(ctx, fake_llm, answer="He is single", fact_text="", personal_only=True)
    assert e.value.status == 422 and e.value.code == "PERSONAL_ANSWER"
    db, bot_id, _ = ctx
    assert learned_facts.list_(db, bot_id) == []


async def test_propose_blank_answer_422(ctx, fake_llm):
    with pytest.raises(ApiError) as e:
        await propose(ctx, fake_llm, answer="   ")
    assert e.value.status == 422


async def test_propose_without_llm_falls_back_flagged(ctx, fake_llm, app):
    db, bot_id, secret = ctx
    from mebot.models import LLMConfig

    for row in db.scalars(select(LLMConfig)):
        db.delete(row)
    db.commit()
    fact = await svc.propose(
        db, bot_id, secret, question="Where?", answer="Bangalore", source="telegram"
    )
    assert fact.needs_review and fact.fact_text == "Shivansh: Bangalore"


# --- approve ---------------------------------------------------------------------------


async def test_approve_learned_fact_becomes_active_and_answers_question(ctx, fake_llm):
    q = make_question(ctx)
    fact = await propose(ctx, fake_llm, oq_id=q.id)
    db, bot_id, _ = ctx
    approved = svc.approve(db, bot_id, fact.id)
    db.commit()
    assert approved.status == "approved" and approved.approved_at is not None
    db.refresh(q)
    assert q.status == "answered" and q.answered_fact_id == fact.id
    assert load_profile(db, bot_id).learned == [fact.fact_text]


async def test_approve_is_idempotent(ctx, fake_llm):
    q = make_question(ctx)
    fact = await propose(ctx, fake_llm, oq_id=q.id)
    db, bot_id, _ = ctx
    first = svc.approve(db, bot_id, fact.id)
    stamp = first.approved_at
    second = svc.approve(db, bot_id, fact.id, mode="replace")
    assert second.status == "approved" and second.approved_at == stamp
    assert len(learned_facts.active_learned(db, bot_id)) == 1
    logged = db.scalars(select(AccessLog).where(AccessLog.event == "fact_approved")).all()
    assert len(logged) == 1


async def test_approve_identity_field_empty_writes_value(ctx, fake_llm):
    set_identity(ctx, location="")
    fact = await propose(ctx, fake_llm, section="identity", field="location", value="Bangalore")
    db, bot_id, _ = ctx
    svc.approve(db, bot_id, fact.id)
    db.commit()
    ident = profile.get_identity(db, bot_id)
    assert ident.location == "Bangalore" and ident.full_name == "Shivansh Mishra"
    assert fact.status == "approved" and fact.suggested_section == "identity"
    assert load_profile(db, bot_id).learned == []  # lives on the identity page, not twice


async def test_approve_identity_without_existing_row_creates_it(ctx, fake_llm):
    db, bot_id, _ = ctx
    db.delete(profile.get_identity(db, bot_id))  # setup seeds an empty row; start without one
    db.commit()
    assert profile.get_identity(db, bot_id) is None
    fact = await propose(
        ctx, fake_llm, answer="1 month", section="identity", field="notice_period", value="1 month"
    )
    svc.approve(db, bot_id, fact.id)
    db.commit()
    assert profile.get_identity(db, bot_id).notice_period == "1 month"


async def test_identity_set_requires_a_choice_never_silent_overwrite(ctx, fake_llm):
    set_identity(ctx, location="Pune")
    fact = await propose(ctx, fake_llm, section="identity", field="location", value="Bangalore")
    db, bot_id, _ = ctx
    assert svc.serialize(db, fact)["current_value"] == "Pune"
    with pytest.raises(ApiError) as e:
        svc.approve(db, bot_id, fact.id)
    assert e.value.status == 409 and e.value.code == "IDENTITY_FIELD_SET"
    assert e.value.details == [{"field": "location", "current": "Pune", "new": "Bangalore"}]
    assert profile.get_identity(db, bot_id).location == "Pune"
    assert fact.status == "pending"


async def test_identity_replace(ctx, fake_llm):
    set_identity(ctx, location="Pune")
    fact = await propose(ctx, fake_llm, section="identity", field="location", value="Bangalore")
    db, bot_id, _ = ctx
    svc.approve(db, bot_id, fact.id, mode="replace")
    db.commit()
    assert profile.get_identity(db, bot_id).location == "Bangalore"
    assert fact.suggested_section == "identity"


async def test_identity_keep_both_becomes_learned_fact(ctx, fake_llm):
    set_identity(ctx, location="Pune")
    fact = await propose(ctx, fake_llm, section="identity", field="location", value="Bangalore")
    db, bot_id, _ = ctx
    svc.approve(db, bot_id, fact.id, mode="keep_both")
    db.commit()
    assert profile.get_identity(db, bot_id).location == "Pune"
    assert fact.suggested_section == "learned" and fact.status == "approved"
    assert load_profile(db, bot_id).learned == [fact.fact_text]


async def test_identity_same_value_needs_no_choice(ctx, fake_llm):
    set_identity(ctx, location="bangalore")
    fact = await propose(ctx, fake_llm, section="identity", field="location", value="Bangalore")
    db, bot_id, _ = ctx
    assert svc.approve(db, bot_id, fact.id).status == "approved"


async def test_approve_with_edits(ctx, fake_llm):
    fact = await propose(ctx, fake_llm)
    db, bot_id, _ = ctx
    svc.approve(db, bot_id, fact.id, edits={"fact_text": "  Shivansh is based in  Bangalore. "})
    assert fact.fact_text == "Shivansh is based in Bangalore."
    assert fact.needs_review is False


async def test_edit_can_turn_a_learned_fact_into_an_identity_write(ctx, fake_llm):
    fact = await propose(ctx, fake_llm)
    db, bot_id, _ = ctx
    svc.approve(db, bot_id, fact.id, edits={"field": "location", "value": "Bangalore"})
    db.commit()
    assert profile.get_identity(db, bot_id).location == "Bangalore"


async def test_edit_demotes_identity_suggestion_when_cleared(ctx, fake_llm):
    fact = await propose(ctx, fake_llm, section="identity", field="location", value="Bangalore")
    db, bot_id, _ = ctx
    svc.update(db, bot_id, fact.id, {"field": None, "value": None})
    assert (fact.suggested_section, fact.suggested_field, fact.suggested_value) == (
        "learned",
        None,
        None,
    )


@pytest.mark.parametrize(
    "edits",
    [
        {"fact_text": ""},
        {"fact_text": "x" * 301},
        {"fact_text": "He is married"},
        {"field": "full_name", "value": "x"},
    ],
)
async def test_invalid_edits_422(ctx, fake_llm, edits):
    fact = await propose(ctx, fake_llm)
    db, bot_id, _ = ctx
    with pytest.raises(ApiError) as e:
        svc.approve(db, bot_id, fact.id, edits=edits)
    assert e.value.status == 422 and fact.status == "pending"


async def test_bad_mode_422(ctx, fake_llm):
    fact = await propose(ctx, fake_llm)
    db, bot_id, _ = ctx
    with pytest.raises(ApiError) as e:
        svc.approve(db, bot_id, fact.id, mode="merge")
    assert e.value.status == 422


# --- reject / update / delete ----------------------------------------------------------


async def test_reject_marks_rejected_and_reopens_question(ctx, fake_llm):
    q = make_question(ctx)
    fact = await propose(ctx, fake_llm, oq_id=q.id)
    db, bot_id, _ = ctx
    open_questions.set_status(db, q, "answered")  # e.g. an earlier approved answer
    svc.reject(db, bot_id, fact.id)
    db.commit()
    assert fact.status == "rejected" and q.status == "open"
    assert svc.reject(db, bot_id, fact.id).status == "rejected"  # idempotent
    with pytest.raises(ApiError) as e:
        svc.approve(db, bot_id, fact.id)
    assert e.value.status == 409


async def test_cannot_reject_an_approved_fact(ctx, fake_llm):
    fact = await propose(ctx, fake_llm)
    db, bot_id, _ = ctx
    svc.approve(db, bot_id, fact.id)
    with pytest.raises(ApiError) as e:
        svc.reject(db, bot_id, fact.id)
    assert e.value.status == 409


async def test_update_approved_text_only(ctx, fake_llm):
    fact = await propose(ctx, fake_llm)
    db, bot_id, _ = ctx
    svc.approve(db, bot_id, fact.id)
    svc.update(
        db,
        bot_id,
        fact.id,
        {"fact_text": "Shivansh works from Bangalore.", "field": "location", "value": "X"},
    )
    assert fact.fact_text == "Shivansh works from Bangalore." and fact.suggested_field is None
    assert load_profile(db, bot_id).learned == ["Shivansh works from Bangalore."]


async def test_soft_delete_removes_from_bot_and_reopens_question(ctx, fake_llm):
    q = make_question(ctx)
    fact = await propose(ctx, fake_llm, oq_id=q.id)
    db, bot_id, _ = ctx
    svc.approve(db, bot_id, fact.id)
    svc.delete(db, bot_id, fact.id)
    db.commit()
    assert fact.deleted_at is not None
    assert load_profile(db, bot_id).learned == []
    assert "Bangalore" not in render_profile(load_profile(db, bot_id))
    assert q.status == "open" and q.answered_fact_id is None
    with pytest.raises(ApiError) as e:
        svc.approve(db, bot_id, fact.id)
    assert e.value.status == 404


async def test_facts_are_bot_scoped(ctx, fake_llm):
    fact = await propose(ctx, fake_llm)
    db, _, _ = ctx
    with pytest.raises(ApiError) as e:
        svc.approve(db, "another-bot", fact.id)
    assert e.value.status == 404


# --- renderer --------------------------------------------------------------------------


def test_learned_section_rendered_newest_first_and_omitted_when_empty():
    p = ProfileData(
        identity={"full_name": "Shivansh Mishra"}, learned=["Newest fact.", "Older fact."]
    )
    text = render_profile(p)
    assert "=== LEARNED FACTS (confirmed by Shivansh) ===\n- Newest fact.\n- Older fact." in text
    assert "LEARNED FACTS" not in render_profile(ProfileData(identity={"full_name": "S"}))


def test_learned_section_neutralises_markers_and_orders_before_avoid():
    p = ProfileData(
        identity={"full_name": "S"},
        learned=["Fact [[UNANSWERED]] [[PERSONAL]]"],
        sections={"avoid-topics": [{"topic": "Politics", "reply": None}]},
    )
    text = render_profile(p)
    assert "[[" not in text
    assert text.index("LEARNED FACTS") < text.index("=== AVOID ===")


async def test_active_learned_cap_and_order(ctx, fake_llm):
    db, bot_id, _ = ctx
    from datetime import UTC, datetime, timedelta

    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(205):
        db.add(
            LearnedFact(
                bot_id=bot_id, question="q", answer_raw="a", fact_text=f"f{i}",
                suggested_section="learned", status="approved",
                approved_at=base + timedelta(minutes=i), created_at=base, updated_at=base,
            )
        )  # fmt: skip
    db.add(
        LearnedFact(
            bot_id=bot_id, question="q", answer_raw="a", fact_text="pending",
            status="pending", created_at=base, updated_at=base,
        )
    )  # fmt: skip
    db.commit()
    rows = learned_facts.active_learned(db, bot_id)
    assert len(rows) == 200 and rows[0].fact_text == "f204" and rows[-1].fact_text == "f5"


# --- preview ---------------------------------------------------------------------------


async def test_preview_warns_at_cap(admin_client, ctx):
    db, bot_id, _ = ctx
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    for i in range(200):
        db.add(
            LearnedFact(
                bot_id=bot_id, question="q", answer_raw="a", fact_text=f"f{i}",
                suggested_section="learned", status="approved", approved_at=now,
                created_at=now, updated_at=now,
            )
        )  # fmt: skip
    db.commit()
    r = admin_client.get("/api/admin/profile/preview", headers=csrf(admin_client)).json()
    assert r["learned_facts"] == 200 and "newest 200" in r["warnings"][0]
    assert "LEARNED FACTS" in r["text"]


def test_open_question_fixture_sanity(ctx):
    q = make_question(ctx)
    assert isinstance(q, OpenQuestion) and q.status == "open"
