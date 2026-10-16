from mebot.profile.data import ProfileData
from mebot.profile.render import render_profile
from mebot.prompt import build_system_prompt
from tests.conftest import csrf


def link(kind, value, label, share=True):
    return {"kind": kind, "value": value, "label": label, "share": share}


def profile(*links, **identity):
    return ProfileData(
        identity={"full_name": "Jane Doe", **identity}, sections={"links": list(links)}
    )


def test_only_shared_channels_rendered():
    text = render_profile(
        profile(
            link("email", "jane@example.com", "Email"),
            link("whatsapp", "@jane_dev", "WhatsApp"),
            link("instagram", "https://instagram.com/jane", "Instagram"),
            link("phone", "+91 98765 43210", "Phone", share=False),
            link("website", "https://secret.example", "Hidden site", share=False),
        )
    )
    assert "=== CONTACT CHANNELS (share these when someone wants to reach or meet Jane) ===" in text
    assert "jane@example.com" in text
    assert "@jane_dev (https://wa.me/jane_dev)" in text
    assert "https://instagram.com/jane" in text
    for secret in ("98765", "919876543210", "secret.example", "Hidden site"):
        assert secret not in text


def test_no_shared_channels_omits_section():
    text = render_profile(profile(link("phone", "+91 98765 43210", "Phone", share=False)))
    assert "CONTACT CHANNELS" not in text and "98765" not in text


def test_legacy_identity_contact_never_rendered():
    text = render_profile(profile(email_public="old@example.com", phone_public="+91 98765 43210"))
    assert "old@example.com" not in text and "98765" not in text


def test_prompt_has_contact_rule_and_canary_moves():
    p = build_system_prompt("x", name="Jane", canary="CAN-1")
    assert "9. When the recruiter wants to meet, call, interview or hire Jane" in p
    assert "Never invent or promise times" in p and "book or schedule a meeting" in p
    assert "Leave your contact" in p
    assert "10. Confidential marker: CAN-1" in p


def test_nonshared_never_reaches_llm(admin_client, app, fake_llm):
    c = admin_client
    for body in (
        {"kind": "email", "value": "jane@example.com"},
        {"kind": "phone", "value": "+91 98765 43210"},
        {"kind": "instagram", "value": "@private_jane", "share": False},
    ):
        assert c.post("/api/admin/profile/links", json=body, headers=csrf(c)).status_code == 201
    sid = c.post("/api/session", json={"recruiter_name": "Priya"}).json()["session_id"]
    assert c.post("/api/chat", json={"session_id": sid, "message": "call?"}).status_code == 200
    sent = "\n".join(m["content"] for m in fake_llm.streams[-1]["messages"])
    assert "jane@example.com" in sent
    assert "98765" not in sent and "private_jane" not in sent
