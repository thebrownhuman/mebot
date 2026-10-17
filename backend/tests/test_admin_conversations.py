import csv
import io
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from mebot import conversations as conv
from mebot.models import AccessLog, Bot
from tests.conftest import csrf
from tests.dash_helpers import bot_id, counts, seed_session

Q = [("user", "What is his tech stack?"), ("assistant", "Python and React.")]
URL = "/api/admin/conversations"


def ago(days, hours=0):
    return datetime.now(UTC) - timedelta(days=days, hours=hours)


def ids(r):
    assert r.status_code == 200, r.text
    return [i["id"] for i in r.json()["items"]]


def test_list_shape_and_order(admin_client, app):
    a = seed_session(app, ago(3), Q, name="Ann", origin="https://shivansh.dev")
    b = seed_session(app, ago(1), Q + Q, name="Bob")
    body = admin_client.get(URL).json()
    assert [i["id"] for i in body["items"]] == [b, a] and body["next_cursor"] is None
    item = body["items"][1]
    assert item["recruiter_name"] == "Ann" and item["messages"] == 2
    assert item["origin"] == "https://shivansh.dev" and item["preview"] == Q[0][1]
    assert item["flags"] == [] and item["started_at"].endswith("Z")
    assert body["items"][0]["origin"] == "direct" and body["items"][0]["messages"] == 4


def test_empty_sessions_are_listed(admin_client, app):
    sid = seed_session(app, ago(1), [])
    [item] = admin_client.get(URL).json()["items"]
    assert item["id"] == sid and item["messages"] == 0 and item["preview"] == ""


def test_flags_and_has_filters(admin_client, app):
    plain = seed_session(app, ago(1), Q)
    un = seed_session(app, ago(2), Q, unanswered=True)
    ct = seed_session(app, ago(3), Q, contact=True)
    ow = seed_session(app, ago(4), Q, owner_reply=True)
    lk = seed_session(app, ago(5), Q, events=[("LEAK_BLOCKED", None)])
    rd = seed_session(app, ago(6), Q, events=[("CHANNEL_REDACTED", "2")])
    assert ids(admin_client.get(f"{URL}?has=unanswered")) == [un]
    assert ids(admin_client.get(f"{URL}?has=contact")) == [ct]
    assert ids(admin_client.get(f"{URL}?has=owner_reply")) == [ow]
    assert ids(admin_client.get(f"{URL}?has=leak_blocked")) == [lk]
    assert ids(admin_client.get(f"{URL}?has=contact,owner_reply")) == []  # AND
    flags = {i["id"]: i["flags"] for i in admin_client.get(f"{URL}?limit=100").json()["items"]}
    assert flags[plain] == [] and flags[un] == ["unanswered"] and flags[ct] == ["contact"]
    assert flags[ow] == ["owner_reply"] and flags[lk] == ["leak_blocked"]
    assert flags[rd] == ["redacted"]
    assert admin_client.get(f"{URL}?has=bogus").status_code == 422


def test_range_and_custom_dates(admin_client, app):
    new = seed_session(app, ago(1), Q)
    mid = seed_session(app, ago(20), Q)
    old = seed_session(app, ago(60), Q)
    assert ids(admin_client.get(f"{URL}?range=7d")) == [new]
    assert ids(admin_client.get(f"{URL}?range=30d")) == [new, mid]
    assert set(ids(admin_client.get(f"{URL}?range=90d"))) == {new, mid, old}
    assert len(ids(admin_client.get(URL))) == 3  # no range = all time
    day = (ago(20)).date().isoformat()
    assert ids(admin_client.get(f"{URL}?from={day}&to={day}")) == [mid]
    assert ids(admin_client.get(f"{URL}?from={day}")) == [new, mid]
    assert admin_client.get(f"{URL}?range=1y").status_code == 422
    assert admin_client.get(f"{URL}?from=nope").status_code == 422
    assert admin_client.get(f"{URL}?from=2026-10-02&to=2026-10-01").status_code == 422


def test_custom_dates_use_bot_timezone(admin_client, app):
    # 20:00 UTC Oct 16 = 01:30 Oct 17 in Kolkata: only "Oct 17" there.
    sid = seed_session(app, datetime(2026, 10, 16, 20, tzinfo=UTC), Q)
    assert ids(admin_client.get(f"{URL}?from=2026-10-17&to=2026-10-17")) == []
    with app.state.session_factory() as db:
        db.get(Bot, bot_id(app)).timezone = "Asia/Kolkata"
        db.commit()
    assert ids(admin_client.get(f"{URL}?from=2026-10-17&to=2026-10-17")) == [sid]


def test_origin_filter(admin_client, app):
    a = seed_session(app, ago(1), Q, origin="https://shivansh.dev")
    d = seed_session(app, ago(2), Q)
    seed_session(app, ago(3), Q, origin="https://other.example")
    assert ids(admin_client.get(f"{URL}?origin=https://shivansh.dev")) == [a]
    assert ids(admin_client.get(f"{URL}?origin=direct")) == [d]


def test_search_is_case_insensitive_and_escapes_wildcards(admin_client, app):
    k = seed_session(app, ago(1), [("user", "Do you know KUBERNETES?"), ("assistant", "yes")])
    pct = seed_session(app, ago(2), [("user", "100% remote?"), ("assistant", "yes")])
    seed_session(app, ago(3), [("user", "100 remote"), ("assistant", "no")])
    us = seed_session(app, ago(4), [("user", "snake_case rules"), ("assistant", "ok")])
    seed_session(app, ago(5), [("user", "snakeXcase"), ("assistant", "ok")])
    assert ids(admin_client.get(f"{URL}?q=kubernetes")) == [k]
    assert ids(admin_client.get(f"{URL}?q=100%25")) == [pct]
    assert ids(admin_client.get(f"{URL}?q=snake_case")) == [us]
    assert ids(admin_client.get(f"{URL}?q=%25%25")) == []  # a literal "%%"
    assert ids(admin_client.get(f"{URL}?q=nomatchhere")) == []
    assert admin_client.get(f"{URL}?q=a").status_code == 422
    assert admin_client.get(f"{URL}?q=%20a%20").status_code == 422


def test_cursor_pagination_is_stable_with_ties(admin_client, app):
    same = ago(1)
    made = [seed_session(app, same, Q) for _ in range(5)]
    made += [seed_session(app, ago(2 + i), Q) for i in range(3)]
    seen, cursor = [], None
    for _ in range(10):
        url = f"{URL}?limit=3" + (f"&cursor={cursor}" if cursor else "")
        body = admin_client.get(url).json()
        seen += [i["id"] for i in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == 8 and set(seen) == set(made)
    assert seen[:5] == sorted(made[:5], reverse=True)  # ties break on id, newest first
    # a session added mid-walk doesn't shift later pages
    first = admin_client.get(f"{URL}?limit=3").json()
    seed_session(app, ago(0), Q)
    second = admin_client.get(f"{URL}?limit=3&cursor={first['next_cursor']}").json()
    assert not {i["id"] for i in first["items"]} & {i["id"] for i in second["items"]}
    assert admin_client.get(f"{URL}?cursor=garbage").status_code == 422


def test_limit_bounds(admin_client):
    assert admin_client.get(f"{URL}?limit=0").status_code == 422
    assert admin_client.get(f"{URL}?limit=101").status_code == 422


def test_detail(admin_client, app):
    sid = seed_session(
        app, ago(1), Q, unanswered=True, contact=True, origin="https://shivansh.dev",
        owner_reply=True,
    )
    d = admin_client.get(f"{URL}/{sid}").json()
    assert d["id"] == sid and d["origin"] == "https://shivansh.dev"
    roles = [(m["role"], m["unanswered"], m["from_owner"]) for m in d["messages"]]
    assert roles == [
        ("user", False, False),
        ("assistant", True, False),
        ("assistant", False, True),
    ]
    names = {e["event"] for e in d["events"]}
    assert {"UNANSWERED", "OWNER_REPLIED", "CONTACT_LEFT", "WIDGET_OPENED"} <= names
    assert d["contact"]["email"] == "r@example.com"
    assert "ip" not in json.dumps(d)


def test_detail_unknown_is_404(admin_client):
    r = admin_client.get(f"{URL}/nope")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"


def test_delete_removes_everything_linked(admin_client, app):
    keep = seed_session(app, ago(1), Q, contact=True)
    gone = seed_session(app, ago(2), Q, contact=True, unanswered=True, origin="https://a.example")
    before = counts(app)
    r = admin_client.delete(f"{URL}/{gone}", headers=csrf(admin_client))
    assert r.status_code == 204
    after = counts(app)
    assert after["sessions"] == before["sessions"] - 1
    assert after["messages"] == before["messages"] - 2 and after["contacts"] == 1
    with app.state.session_factory() as db:
        assert not db.scalars(select(AccessLog).where(AccessLog.session_id == gone)).all()
        assert db.scalars(select(AccessLog).where(AccessLog.session_id == keep)).all()
    assert admin_client.get(f"{URL}/{gone}").status_code == 404
    assert admin_client.delete(f"{URL}/{gone}", headers=csrf(admin_client)).status_code == 404


def test_delete_needs_csrf(admin_client, app):
    sid = seed_session(app, ago(1), Q)
    assert admin_client.delete(f"{URL}/{sid}").status_code == 403
    assert counts(app)["sessions"] == 1


def test_scoped_to_bot(admin_client, app):
    from mebot.models import ChatSession

    with app.state.session_factory() as db:
        db.add(ChatSession(id="foreign", bot_id="other-bot"))
        db.commit()
    assert ids(admin_client.get(URL)) == []
    assert admin_client.get(f"{URL}/foreign").status_code == 404
    assert admin_client.delete(f"{URL}/foreign", headers=csrf(admin_client)).status_code == 404


def test_old_session_endpoints_still_work_but_are_deprecated(admin_client, app):
    sid = seed_session(app, ago(1), Q)
    r = admin_client.get("/api/admin/sessions")
    assert r.status_code == 200 and r.json()[0]["id"] == sid and r.headers["deprecation"] == "true"
    r = admin_client.get(f"/api/admin/sessions/{sid}/messages")
    assert r.status_code == 200 and len(r.json()) == 2 and r.headers["deprecation"] == "true"


# --- export ---------------------------------------------------------------------------------


def rows_of(r):
    assert r.status_code == 200, r.text
    text = r.content.decode("utf-8")
    assert text.startswith("﻿")
    return list(csv.DictReader(io.StringIO(text.lstrip("﻿"))))


def test_csv_export_content_and_headers(admin_client, app):
    sid = seed_session(
        app, ago(1), [("user", "hi, \"there\"\nline2"), ("assistant", "hello")],
        name="Ann", origin="https://shivansh.dev", unanswered=True,
    )
    seed_session(app, ago(2), Q, name="Bob")
    r = admin_client.get(f"{URL}/export?format=csv&range=7d")
    cd = r.headers["content-disposition"]
    assert cd.startswith('attachment; filename="mebot-conversations-') and cd.endswith('.csv"')
    assert r.headers["content-type"].startswith("text/csv")
    rows = rows_of(r)
    assert list(rows[0]) == list(conv.CSV_COLUMNS)
    assert len(rows) == 4
    ann = [x for x in rows if x["session_id"] == sid]
    assert ann[0]["content"] == 'hi, "there"\nline2' and ann[0]["role"] == "user"
    assert ann[0]["recruiter_name"] == "Ann" and ann[0]["origin"] == "https://shivansh.dev"
    assert ann[1]["unanswered"] == "true" and ann[0]["unanswered"] == "false"
    assert {x["origin"] for x in rows if x["session_id"] != sid} == {"direct"}


def test_export_respects_filters(admin_client, app):
    seed_session(app, ago(1), [("user", "kubernetes?"), ("assistant", "yes")])
    seed_session(app, ago(2), Q)
    rows = rows_of(admin_client.get(f"{URL}/export?q=kubernetes"))
    assert len(rows) == 2 and rows[0]["content"] == "kubernetes?"


@pytest.mark.parametrize("lead", ["=", "+", "-", "@"])
def test_csv_formula_injection_neutralised(admin_client, app, lead):
    seed_session(
        app, ago(1), [("user", f'{lead}HYPERLINK("http://evil","x")'), ("assistant", "ok")],
        name=f"{lead}cmd|calc",
    )
    rows = rows_of(admin_client.get(f"{URL}/export"))
    assert rows[0]["content"].startswith("'" + lead)
    assert rows[0]["recruiter_name"] == "'" + lead + "cmd|calc"


def test_json_export(admin_client, app):
    sid = seed_session(app, ago(1), Q, name="Ann")
    r = admin_client.get(f"{URL}/export?format=json")
    assert r.headers["content-type"].startswith("application/json")
    assert r.headers["content-disposition"].endswith('.json"')
    data = json.loads(r.content)
    assert [m["role"] for m in data] == ["user", "assistant"]
    assert data[0]["session_id"] == sid and data[0]["unanswered"] is False
    assert json.loads(admin_client.get(f"{URL}/export?format=json&q=zzzz").content) == []


def test_export_format_validated(admin_client):
    assert admin_client.get(f"{URL}/export?format=xml").status_code == 422


def test_export_over_limit_is_422_with_hint(admin_client, app, monkeypatch):
    monkeypatch.setattr(conv, "MAX_EXPORT_MESSAGES", 3)
    seed_session(app, ago(1), Q + Q)
    r = admin_client.get(f"{URL}/export")
    assert r.status_code == 422 and r.json()["error"]["code"] == "EXPORT_TOO_LARGE"
    assert "shorter date range" in r.json()["error"]["message"]
    assert len(rows_of(admin_client.get(f"{URL}/export?q=stack&has=contact"))) == 0


def test_export_requires_login(client):
    assert client.get(f"{URL}/export").status_code in (401, 403, 503)
