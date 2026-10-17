import base64
from datetime import timedelta

import pytest

from app import signing
from app.auth import AuthError, verify_signed
from app.db import Database, iso
from tests.helpers import NOW, VECTORS, Install


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "r.db")


def pin(db, inst: Install):
    with db.tx() as c:
        c.execute(
            "INSERT INTO installs VALUES (?, ?, ?, ?, '0.9.0', 'single')",
            (inst.install_id, inst.public_key, iso(NOW), iso(NOW)),
        )


def check(
    db,
    inst,
    method="POST",
    path="/v1/heartbeat",
    body=b"{}",
    *,
    at=NOW,
    now=NOW,
    claimed=True,
    headers=None,
):
    return verify_signed(
        headers=headers or inst.headers(method, path, body, at=at),
        method=method,
        path=path,
        body=body,
        db=db,
        now=now,
        claimed_key=inst.public_key if claimed else None,
    )


def code(exc: pytest.ExceptionInfo) -> str:
    return exc.value.code


def test_vectors_verify():
    raw = base64.b64decode(VECTORS["public_key_b64"])
    assert signing.install_id_for(raw) == VECTORS["install_id"]
    assert len(VECTORS["cases"]) >= 3
    for case in VECTORS["cases"]:
        msg = signing.canonical(
            case["method"], case["path"], case["timestamp"], case["body"].encode()
        )
        assert msg.decode() == case["canonical"]
        assert signing.verify(raw, case["signature_b64"], msg)
        assert not signing.verify(raw, case["signature_b64"], msg + b"x")


def test_canonical_form():
    assert signing.canonical("post", "/v1/x", "1", b"").decode() == (
        "POST\n/v1/x\n1\ne3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_first_contact_pins_and_verifies(db):
    inst = Install()
    v = check(db, inst)
    assert v.install_id == inst.install_id and v.is_new is True


def test_known_install_verifies_without_claimed_key(db):
    inst = Install()
    pin(db, inst)
    v = check(db, inst, "DELETE", "/v1/register", b"", claimed=False)
    assert v.is_new is False


def test_unknown_install_without_key_is_rejected(db):
    with pytest.raises(AuthError) as e:
        check(db, Install(), "DELETE", "/v1/register", b"", claimed=False)
    assert code(e) == "UNKNOWN_INSTALL"


def test_wrong_key_for_pinned_install(db):
    owner, attacker = Install(), Install()
    pin(db, owner)
    # signs with their own key but claims the owner's install id
    headers = attacker.headers("DELETE", "/v1/register", b"", install_id=owner.install_id)
    with pytest.raises(AuthError) as e:
        check(db, owner, "DELETE", "/v1/register", b"", claimed=False, headers=headers)
    assert code(e) == "SIGNATURE_INVALID"


def test_pinned_key_cannot_be_replaced_by_body(db):
    owner, attacker = Install(), Install()
    pin(db, owner)
    headers = attacker.headers("POST", "/v1/heartbeat", b"{}", install_id=owner.install_id)
    with pytest.raises(AuthError) as e:
        verify_signed(
            headers=headers,
            method="POST",
            path="/v1/heartbeat",
            body=b"{}",
            db=db,
            now=NOW,
            claimed_key=attacker.public_key,
        )
    assert code(e) == "KEY_MISMATCH"


def test_install_id_must_match_key(db):
    a, b = Install(), Install()
    headers = a.headers("POST", "/v1/heartbeat", b"{}", install_id=b.install_id)
    with pytest.raises(AuthError) as e:
        check(db, a, headers=headers)
    assert code(e) == "SIGNATURE_INVALID"


@pytest.mark.parametrize(
    "delta", [timedelta(seconds=301), -timedelta(seconds=301), timedelta(days=1)]
)
def test_clock_skew_beyond_five_minutes(db, delta):
    inst = Install()
    with pytest.raises(AuthError) as e:
        check(db, inst, at=NOW + delta)
    assert code(e) == "TIMESTAMP_SKEW"


@pytest.mark.parametrize("delta", [timedelta(seconds=299), -timedelta(seconds=299)])
def test_clock_skew_within_five_minutes(db, delta):
    check(db, Install(), at=NOW + delta)


def test_replay_is_rejected(db):
    inst = Install()
    headers = inst.headers("POST", "/v1/heartbeat", b"{}")
    check(db, inst, headers=headers)
    with pytest.raises(AuthError) as e:
        check(db, inst, headers=headers)
    assert code(e) == "REPLAYED"


def test_nonce_expires_after_ten_minutes(db):
    inst = Install()
    headers = inst.headers("POST", "/v1/heartbeat", b"{}")
    check(db, inst, headers=headers)
    # past the skew window the replay is refused by the timestamp rule anyway; the nonce row
    # itself must be gone so the table cannot grow without bound
    later = NOW + timedelta(seconds=signing.NONCE_TTL_SECONDS + 1)
    other = Install()
    check(db, other, now=later, at=later)
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM nonces").fetchone()[0] == 1


def test_failed_signature_does_not_burn_the_nonce(db):
    inst = Install()
    headers = inst.headers("POST", "/v1/heartbeat", b"{}")
    with pytest.raises(AuthError):
        check(db, inst, body=b"tampered", headers=headers)
    check(db, inst, headers=headers)  # the genuine request still goes through


@pytest.mark.parametrize(
    "mutate",
    [
        lambda h: h.pop(signing.HEADER_SIGNATURE),
        lambda h: h.pop(signing.HEADER_TIMESTAMP),
        lambda h: h.pop(signing.HEADER_INSTALL),
        lambda h: h.update({signing.HEADER_TIMESTAMP: "yesterday"}),
        lambda h: h.update({signing.HEADER_INSTALL: "nothex"}),
        lambda h: h.update({signing.HEADER_SIGNATURE: "!!!"}),
    ],
)
def test_malformed_headers(db, mutate):
    inst = Install()
    headers = inst.headers("POST", "/v1/heartbeat", b"{}")
    mutate(headers)
    with pytest.raises(AuthError):
        check(db, inst, headers=headers)


def test_method_and_path_are_signed(db):
    inst = Install()
    headers = inst.headers("POST", "/v1/heartbeat", b"{}")
    with pytest.raises(AuthError):
        check(db, inst, "POST", "/v1/register", b"{}", headers=headers)
    with pytest.raises(AuthError):
        check(db, inst, "DELETE", "/v1/heartbeat", b"{}", headers=headers)
