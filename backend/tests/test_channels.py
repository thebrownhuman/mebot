import pytest

from mebot import channels
from mebot.channels import Channel, ChannelError, normalize


@pytest.mark.parametrize(
    "kind,raw,stored",
    [
        ("email", " Jane@Example.com ", "jane@example.com"),
        ("phone", "+91 98765 43210", "+91 98765 43210"),
        ("whatsapp", "@jane_dev", "@jane_dev"),
        ("whatsapp", "jane_dev", "@jane_dev"),
        ("whatsapp", "wa.me/jane_dev", "@jane_dev"),
        ("whatsapp", "https://wa.me/jane_dev", "@jane_dev"),
        ("instagram", "@jane", "https://instagram.com/jane"),
        ("instagram", "https://www.instagram.com/jane/?hl=en", "https://instagram.com/jane"),
        ("x", "jane", "https://x.com/jane"),
        ("x", "https://twitter.com/jane", "https://x.com/jane"),
        ("telegram", "@jane", "https://t.me/jane"),
        ("github", "jane", "https://github.com/jane"),
        ("github", "https://github.com/jane/repo", "https://github.com/jane"),
        ("portfolio", "https://jane.dev", "https://jane.dev"),
        ("linkedin", "https://linkedin.com/in/jane", "https://linkedin.com/in/jane"),
    ],
)
def test_normalize_ok(kind, raw, stored):
    assert normalize(kind, raw) == stored


@pytest.mark.parametrize(
    "kind,raw",
    [
        ("email", "nope"),
        ("phone", "abc"),
        ("phone", "123"),
        ("phone", "1" * 20),
        ("portfolio", "javascript:alert(1)"),
        ("website", "data:text/html,x"),
        ("website", "example.com"),
        ("instagram", "https://evil.com/jane"),
        ("instagram", "a b"),
        ("telegram", ""),
        ("nonsense", "x"),
    ],
)
def test_normalize_rejects(kind, raw):
    with pytest.raises(ChannelError):
        normalize(kind, raw)


@pytest.mark.parametrize("raw", ["+91 98765 43210", "9876543210", "wa.me/9876543210", "@9876543210"])
def test_whatsapp_number_rejected_with_guidance(raw):
    with pytest.raises(ChannelError) as e:
        normalize("whatsapp", raw)
    assert str(e.value) == channels.WHATSAPP_NUMBER_MSG


def test_display_and_href():
    c = Channel("whatsapp", "WhatsApp", "@jane", True)
    assert (c.display, c.href) == ("@jane", "https://wa.me/jane")
    c = Channel("email", "Email", "j@x.com", True)
    assert (c.display, c.href) == ("j@x.com", "mailto:j@x.com")
    c = Channel("instagram", "IG", "https://instagram.com/jane", True)
    assert (c.display, c.href) == ("@jane", "https://instagram.com/jane")
    c = Channel("portfolio", "Site", "https://jane.dev/", True)
    assert c.display == "jane.dev"


def test_infer_kind():
    assert channels.infer_kind("https://www.linkedin.com/in/x") == "linkedin"
    assert channels.infer_kind("https://github.com/x") == "github"
    assert channels.infer_kind("https://instagram.com/x") == "instagram"
    assert channels.infer_kind("https://evilgithub.com/x") == "website"
    assert channels.infer_kind("https://jane.dev") == "website"


def test_phone_variants():
    v = channels.variants(Channel("phone", "Phone", "+91 98765-43210", False))
    assert {"919876543210", "+919876543210"} <= v
    assert "+91 98765-43210" in v


def test_handle_variants_skip_short():
    v = channels.variants(Channel("instagram", "IG", "https://instagram.com/jane_x", False))
    assert {"jane_x", "@jane_x", "instagram.com/jane_x"} <= v
    assert not channels.variants(Channel("x", "X", "https://x.com/ab", False)) & {"ab"}
