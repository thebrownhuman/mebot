import hashlib
from datetime import timedelta

import pytest
from sqlalchemy import select

from mebot.auth import passwords
from mebot.db import make_session_factory, run_migrations
from mebot.limits.memory import LoginLimiter as InMemoryLoginLimiter
from mebot.models import AdminSession, utcnow
from mebot.repos import admin_sessions, admins


@pytest.fixture
def db(tmp_path):
    url = f"sqlite:///{(tmp_path / 'c.db').as_posix()}"
    run_migrations(url)
    with make_session_factory(url)() as s:
        yield s


# --- passwords ---------------------------------------------------------------


def test_hash_is_argon2id_and_verifies():
    h = passwords.hash_password("correct horse battery")
    assert h.startswith("$argon2id$")
    assert passwords.verify_password(h, "correct horse battery")
    assert not passwords.verify_password(h, "wrong password!")


def test_verify_garbage_hash_is_false():
    assert not passwords.verify_password("not-a-hash", "whatever123")


def test_dummy_verify_runs():
    passwords.dummy_verify("anything")  # must not raise


# --- admins repo -------------------------------------------------------------


def test_admin_email_lowercased_and_lookup(db):
    a = admins.create(db, "Me@Example.COM", "h")
    db.commit()
    assert a.email == "me@example.com"
    assert admins.get_by_email(db, "ME@example.com").id == a.id
    assert admins.exists(db)


def test_soft_deleted_admin_hidden(db):
    a = admins.create(db, "x@example.com", "h")
    a.deleted_at = utcnow()
    db.commit()
    assert admins.get_by_email(db, "x@example.com") is None
    assert not admins.exists(db)


# --- admin sessions ----------------------------------------------------------


def test_session_token_stored_hashed(db):
    token = admin_sessions.create(db, "admin1", ip_hash="h", user_agent="ua")
    db.commit()
    assert len(token) >= 40
    row = db.scalar(select(AdminSession))
    assert row.id == hashlib.sha256(token.encode()).hexdigest()
    assert row.id != token
    assert row.expires_at - row.created_at == timedelta(days=14)


def test_resolve_valid_unknown_and_expired(db):
    token = admin_sessions.create(db, "admin1")
    db.commit()
    assert admin_sessions.resolve(db, token).admin_id == "admin1"
    assert admin_sessions.resolve(db, "nope") is None
    later = utcnow() + timedelta(days=15)
    assert admin_sessions.resolve(db, token, now=later) is None
    assert db.scalar(select(AdminSession)) is None  # expired row purged


def test_sliding_refresh_only_when_under_7_days(db):
    token = admin_sessions.create(db, "admin1")
    db.commit()
    first = db.scalar(select(AdminSession)).expires_at
    s = admin_sessions.resolve(db, token, now=utcnow() + timedelta(days=3))
    assert s.expires_at == first  # 11 days left: untouched
    t = utcnow() + timedelta(days=8)
    s = admin_sessions.resolve(db, token, now=t)
    assert s.expires_at == t + timedelta(days=14)
    assert s.last_seen_at == t


def test_revoke_and_revoke_others(db):
    keep = admin_sessions.create(db, "a")
    drop = admin_sessions.create(db, "a")
    other = admin_sessions.create(db, "b")
    db.commit()
    admin_sessions.revoke_all(db, "a", except_token=keep)
    assert admin_sessions.resolve(db, keep) is not None
    assert admin_sessions.resolve(db, drop) is None
    assert admin_sessions.resolve(db, other) is not None
    admin_sessions.revoke(db, keep)
    assert admin_sessions.resolve(db, keep) is None


def test_purge_expired(db):
    admin_sessions.create(db, "a")
    db.commit()
    assert admin_sessions.purge_expired(db, now=utcnow() + timedelta(days=20)) == 1


# --- rate limit ----------------------------------------------------------------


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_ip_limit_5_per_15_min():
    clock = Clock()
    rl = InMemoryLoginLimiter(clock=clock)
    for i in range(5):
        assert rl.retry_after("1.1.1.1", f"u{i}@x.com") is None
        rl.record_failure("1.1.1.1", f"u{i}@x.com")
    wait = rl.retry_after("1.1.1.1", "new@x.com")
    assert wait is not None and 0 < wait <= 900
    assert rl.retry_after("2.2.2.2", "new@x.com") is None
    clock.t += 901
    assert rl.retry_after("1.1.1.1", "new@x.com") is None


def test_email_limit_10_per_15_min_across_ips():
    rl = InMemoryLoginLimiter(clock=Clock())
    for i in range(10):
        rl.record_failure(f"10.0.0.{i}", "Target@x.com")
    assert rl.retry_after("9.9.9.9", "target@x.com") is not None
