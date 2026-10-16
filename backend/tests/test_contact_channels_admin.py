import pytest

from mebot import channels
from tests.conftest import csrf

BASE = "/api/admin/profile/links"


def post(c, body):
    return c.post(BASE, json=body, headers=csrf(c))


def put(c, id_, body):
    return c.put(f"{BASE}/{id_}", json=body, headers=csrf(c))


def test_create_each_kind_normalises(admin_client):
    r = post(admin_client, {"kind": "instagram", "value": "@jane"})
    assert r.status_code == 201
    got = r.json()
    assert got["value"] == "https://instagram.com/jane"
    assert got["label"] == "Instagram" and got["share"] is True and got["kind"] == "instagram"
    assert post(admin_client, {"kind": "email", "value": "J@X.com"}).json()["value"] == "j@x.com"


def test_phone_defaults_to_not_shared(admin_client):
    r = post(admin_client, {"kind": "phone", "value": "+91 98765 43210"})
    assert r.status_code == 201 and r.json()["share"] is False


def test_phone_share_needs_confirmation(admin_client):
    r = post(admin_client, {"kind": "phone", "value": "+91 98765 43210", "share": True})
    assert r.status_code == 422 and r.json()["error"]["code"] == "CONFIRM_REQUIRED"
    pid = post(admin_client, {"kind": "phone", "value": "+91 98765 43210"}).json()["id"]
    r = put(admin_client, pid, {"share": True})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "CONFIRM_REQUIRED"
    assert (
        r.json()["error"]["message"]
        == "Confirm you want to share your phone number with recruiters."
    )
    r = put(admin_client, pid, {"share": True, "confirm_share_phone": True})
    assert r.status_code == 200 and r.json()["share"] is True
    assert "confirm_share_phone" not in r.json()
    # Already shared: editing the label needs no new confirmation; turning off never does.
    assert put(admin_client, pid, {"label": "Mobile"}).json()["share"] is True
    assert put(admin_client, pid, {"share": False}).json()["share"] is False


def test_partial_put_keeps_other_fields(admin_client):
    cid = post(admin_client, {"kind": "email", "value": "j@x.com", "label": "Work"}).json()["id"]
    got = put(admin_client, cid, {"share": False}).json()
    assert (got["value"], got["label"], got["kind"], got["share"]) == (
        "j@x.com", "Work", "email", False,
    )  # fmt: skip


def test_whatsapp_number_rejected(admin_client):
    r = post(admin_client, {"kind": "whatsapp", "value": "+91 98765 43210"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "VALIDATION_ERROR"
    assert any(
        d["field"] == "value" and channels.WHATSAPP_NUMBER_MSG in d["message"]
        for d in err["details"]
    ), err


@pytest.mark.parametrize(
    "kind,value",
    [
        ("website", "javascript:alert(1)"),
        ("portfolio", "data:text/html,x"),
        ("email", "nope"),
        ("phone", "abc"),
        ("instagram", "https://evil.example/jane"),
        ("bogus", "x"),
    ],
)
def test_invalid_values_422(admin_client, kind, value):
    r = post(admin_client, {"kind": kind, "value": value})
    assert r.status_code == 422


def test_max_30_channels(admin_client):
    for i in range(30):
        assert (
            post(admin_client, {"kind": "website", "value": f"https://s{i}.dev"}).status_code == 201
        )
    r = post(admin_client, {"kind": "website", "value": "https://one-more.dev"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "LIMIT_REACHED"
