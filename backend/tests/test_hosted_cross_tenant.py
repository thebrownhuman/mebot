"""Cross-tenant suite (hosted mode).

Routes are enumerated from the app's OpenAPI schema, so a new route is covered (or fails
this test until it is classified) without anyone remembering to add it.

- Every owner route with an id in its path: tenant A's session, B's real ids -> 404
  (never 403), exactly the same response as for an id that doesn't exist (a route that
  validates the body first may answer 422, but then identically for both, so it is no
  existence oracle), and B's rows are untouched afterwards.
- Every owner route without ids (GET): A's response never contains B's markers.
- Public routes under /b/{A}: never B's profile, facts or chat.
"""

import re
from datetime import timedelta

import pytest
from conftest import csrf
from fastapi.testclient import TestClient

from mebot import models as m

MARK = "ZQXBOBBYSECRET"  # only in tenant B's data
OWNER_PREFIXES = ("/api/admin", "/api/auth", "/api/hosted")
# Path params whose value is a name, not a tenant id: filled with a valid name.
NAMES = {"section": "skills", "kind": "resume"}
# Valid bodies, so these get past validation and must answer 404 themselves.
BODIES = {
    "/api/admin/open-questions/{qid}/answer": {"answer": "x"},
    "/api/admin/import/jobs/{job_id}/apply": {"decisions": []},
    "/api/admin/learned-facts/{fid}": {"fact_text": "x"},
    "/api/admin/profile/{section}/{item_id}": {"name": "x"},
}
# Routes with ids that aren't owner routes; covered elsewhere in this file / other tests.
PUBLIC_WITH_IDS = {
    "/api/session/{sid}/updates",
    "/api/telegram/webhook/{bot_id}",  # secret-header authenticated, see telegram tests
    "/api/billing/webhook/{provider}",  # signature authenticated, see test_billing_webhook
    "/embed/{slug}",
    "/api/public/widget/{slug}",
    "/api/public/widget/{slug}/launcher",
    "/api/public/widget/{slug}/opened",
}


def _seed(app, bot_id: str, mark: str = MARK) -> dict[str, str]:
    """One row of every id-addressable kind for bot_id, all carrying mark."""
    MARK = mark  # noqa: N806
    now = m.utcnow()
    with app.state.session_factory() as db:
        s = m.ChatSession(id=m.new_id(), bot_id=bot_id, recruiter_name=MARK)
        db.add(s)
        db.flush()
        rows = {
            "sid": s,
            "msg": m.Message(bot_id=bot_id, session_id=s.id, role="user", content=MARK),
            "item_id": m.Skill(bot_id=bot_id, name=MARK),
            "cid": m.Contact(bot_id=bot_id, name=MARK, email="b@x.io", session_id=s.id),
            "qid": m.OpenQuestion(bot_id=bot_id, question=MARK, normalized=MARK.lower()),
            "fid": m.LearnedFact(
                bot_id=bot_id, question=MARK, answer_raw=MARK, fact_text=MARK, status="pending"
            ),
            "job_id": m.ImportJob(
                bot_id=bot_id, kind="resume", status="ready", expires_at=now + timedelta(days=1)
            ),
        }
        for r in rows.values():
            db.add(r)
        db.commit()
        return {k: r.id for k, r in rows.items()}


def _counts(app, bot_id):
    with app.state.session_factory() as db:
        return {
            cls.__name__: db.query(cls).filter(cls.bot_id == bot_id).count()
            for cls in (m.ChatSession, m.Message, m.Skill, m.Contact, m.OpenQuestion,
                        m.LearnedFact, m.ImportJob)
        }  # fmt: skip


def _routes(app):
    for path, ops in app.openapi()["paths"].items():
        for method in ops:
            yield method.upper(), path


@pytest.fixture
def seeded(tenants, hosted_app):
    a, b = tenants
    _seed(hosted_app, a.bot_id, "ZQXALICEOWN")  # A has data of its own too (no "empty means safe")
    ids = _seed(hosted_app, b.bot_id)
    return a, b, ids


def test_every_owner_route_with_ids_is_404_on_foreign_ids(seeded, hosted_app):
    a, b, ids = seeded
    before = _counts(hosted_app, b.bot_id)
    checked, problems = 0, []
    for method, path in _routes(hosted_app):
        params = re.findall(r"{(\w+)}", path)
        if not params:
            continue
        if path in PUBLIC_WITH_IDS or path.startswith("/api/platform"):
            continue  # operator routes: tenant sessions get 401 (tests/test_platform.py)
        assert path.startswith(OWNER_PREFIXES) or path == "/widget-test", (
            f"unclassified route with ids: {method} {path}"
        )
        url = path
        has_id = False
        for p in params:
            if p in NAMES:
                url = url.replace(f"{{{p}}}", NAMES[p])
            elif p in ids:
                url = url.replace(f"{{{p}}}", ids[p])
                has_id = True
            else:
                pytest.fail(f"no foreign id for path param {p!r} in {path}; add it to _seed")
        if not has_id:
            continue
        body = BODIES.get(path, {})
        r = a.client.request(method, url, json=body, headers=csrf(a.client))
        missing = url
        for p in params:
            if p in ids:
                missing = missing.replace(ids[p], "00000000-0000-0000-0000-000000000000")
        r0 = a.client.request(method, missing, json=body, headers=csrf(a.client))
        if path in BODIES and r.status_code != 404:
            problems.append(f"{method} {url} -> {r.status_code}, want 404 with a valid body")
        checked += 1
        if r.status_code not in (404, 422) or (r.status_code, r.text) != (r0.status_code, r0.text):
            problems.append(f"{method} {url} -> {r.status_code} (missing id: {r0.status_code})")
        if MARK in r.text:
            problems.append(f"{method} {url} leaked B's data")
    assert checked >= 15
    assert not problems, "\n".join(problems)
    assert _counts(hosted_app, b.bot_id) == before


def test_owner_routes_without_ids_never_show_other_tenant(seeded, hosted_app):
    a, _, _ = seeded
    problems = []
    for method, path in _routes(hosted_app):
        if method != "GET" or "{" in path or not path.startswith(OWNER_PREFIXES):
            continue
        r = a.client.get(path)
        if MARK in r.text:
            problems.append(f"GET {path} leaked B's data")
    assert not problems, "\n".join(problems)


def test_owner_routes_reject_anonymous(hosted_app, tenants):
    with TestClient(hosted_app) as anon:
        for method, path in _routes(hosted_app):
            if not path.startswith("/api/admin") or "{" in path:
                continue
            r = anon.request(method, path, json={}, headers=csrf(anon))
            assert r.status_code in (401, 403), f"{method} {path} -> {r.status_code}"


def test_public_routes_of_a_never_return_b(seeded, hosted_app):
    a, b, ids = seeded
    with TestClient(hosted_app) as anon:
        for path in ("/api/public/config", "/api/public/contact-channels"):
            r = anon.get(f"/b/{a.slug}{path}")
            assert r.status_code == 200 and MARK not in r.text, path
        # B's chat session id via A's prefix: not found, nothing leaks.
        r = anon.get(f"/b/{a.slug}/api/session/{ids['sid']}/updates")
        assert r.status_code == 404 and MARK not in r.text
        r = anon.post(
            f"/b/{a.slug}/api/chat",
            json={"session_id": ids["sid"], "message": "hi"},
            headers=csrf(anon),
        )
        assert r.status_code == 404 and MARK not in r.text


def test_prompt_for_a_has_no_b_knowledge(seeded, fake_llm, hosted_app):
    a, _, _ = seeded
    with TestClient(hosted_app) as anon:
        sid = anon.post(f"/b/{a.slug}/api/session", json={}, headers=csrf(anon)).json()[
            "session_id"
        ]
        r = anon.post(
            f"/b/{a.slug}/api/chat", json={"session_id": sid, "message": "skills?"},
            headers=csrf(anon),
        )  # fmt: skip
        assert r.status_code == 200, r.text
    prompt = str(fake_llm.streams[-1])
    assert MARK not in prompt
