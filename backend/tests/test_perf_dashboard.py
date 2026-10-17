"""Smoke test: the dashboard stays fast with 100k messages (generous bound, SQLite)."""

import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import insert

from mebot.models import AccessLog, ChatSession, Message
from tests.dash_helpers import bot_id

SESSIONS = 5_000
PER_SESSION = 20  # 100k messages
QUESTIONS = [
    "What is his tech stack?",
    "Does he know Kubernetes?",
    "Is he open to remote work?",
    "How many years of experience?",
]


def _seed(app) -> None:
    bid = bot_id(app)
    now = datetime.now(UTC)
    sessions, messages, logs = [], [], []
    for s in range(SESSIONS):
        sid = uuid.uuid4().hex
        started = now - timedelta(days=s % 28, minutes=s % 600)
        sessions.append(
            {
                "id": sid,
                "bot_id": bid,
                "recruiter_name": f"R{s}",
                "started_at": started,
                "created_at": started,
            }
        )
        if s % 2:
            logs.append(
                {
                    "id": uuid.uuid4().hex,
                    "bot_id": bid,
                    "session_id": sid,
                    "event": "WIDGET_OPENED",
                    "detail": f"https://site{s % 7}.example",
                    "created_at": started,
                }
            )
        for m in range(PER_SESSION):
            user = m % 2 == 0
            text = QUESTIONS[(s + m) % 4] if user else "An answer."
            messages.append(
                {
                    "id": uuid.uuid4().hex,
                    "bot_id": bid,
                    "session_id": sid,
                    "role": "user" if user else "assistant",
                    "content": f"{text} #{s % 50}",
                    "created_at": started + timedelta(seconds=m * 10),
                    "unanswered": (not user) and m % 7 == 1,
                    "from_owner": False,
                }
            )
    with app.state.session_factory() as db:
        for table, rows in ((ChatSession, sessions), (Message, messages), (AccessLog, logs)):
            for i in range(0, len(rows), 10_000):
                db.execute(insert(table), rows[i : i + 10_000])
        db.commit()


def test_overview_and_lists_are_fast_with_100k_messages(admin_client, app):
    _seed(app)
    for rng in ("7d", "30d", "90d"):
        t = time.perf_counter()
        r = admin_client.get(f"/api/admin/analytics/overview?range={rng}")
        took = time.perf_counter() - t
        assert r.status_code == 200 and r.json()["kpis"]["chats"]["value"] > 0
        assert took < 3.0, f"overview {rng} took {took:.2f}s"
    t = time.perf_counter()  # a search with no hit has to look at every message
    r = admin_client.get("/api/admin/conversations?q=zzqqxx")
    assert r.status_code == 200 and r.json()["items"] == []
    assert time.perf_counter() - t < 3.0
    for url in (
        "/api/admin/conversations?limit=25",
        "/api/admin/conversations?q=kubernetes&limit=25",
        "/api/admin/conversations?has=unanswered&range=30d",
    ):
        t = time.perf_counter()
        r = admin_client.get(url)
        took = time.perf_counter() - t
        assert r.status_code == 200 and r.json()["items"], url
        assert took < 3.0, f"{url} took {took:.2f}s"
