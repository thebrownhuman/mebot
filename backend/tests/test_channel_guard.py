import pytest

from mebot.channels import Channel
from mebot.guard.channels import HIDDEN, ChannelGuard

PHONE = Channel("phone", "Phone", "+91 98765 43210", False)
IG = Channel("instagram", "Instagram", "https://instagram.com/jane_private", False)
EMAIL = Channel("email", "Email", "jane@example.com", True)
WA = Channel("whatsapp", "WhatsApp", "@jane_wa", True)


def run(guard, chunks):
    out = "".join(guard.feed(c) for c in chunks)
    return out + guard.finish()


def split_every(text, n):
    return [text[i : i + n] for i in range(0, len(text), n)]


@pytest.mark.parametrize(
    "leak",
    [
        "+91 98765 43210",
        "+919876543210",
        "919876543210",
        "98765 43210",  # shaped like a phone: 10 digits
        "9876543210",
        "+91-98765-43210",
    ],
)
def test_phone_variants_redacted(leak):
    g = ChannelGuard([PHONE, EMAIL])
    out = run(g, [f"Call him on {leak} any time."])
    assert "98765" not in out and "9876" not in out and HIDDEN in out
    assert out.startswith("Call him on ") and out.endswith(" any time.")
    assert g.redactions == 1


def test_handle_variants_redacted_but_shared_email_kept():
    g = ChannelGuard([IG, EMAIL])
    text = "IG: @jane_private / instagram.com/jane_private / jane_private; mail jane@example.com"
    out = run(g, [text])
    assert "jane_private" not in out
    assert "jane@example.com" in out
    assert g.redactions == 3


@pytest.mark.parametrize("n", [1, 2, 3, 5, 7])
def test_value_split_across_chunks(n):
    g = ChannelGuard([PHONE, IG, EMAIL])
    text = "Phone +91 98765 43210, ig @jane_private, mail jane@example.com. Bye."
    out = run(g, split_every(text, n))
    assert "98765" not in out and "jane_private" not in out
    assert out == f"Phone {HIDDEN}, ig {HIDDEN}, mail jane@example.com. Bye."


def test_streaming_releases_text_before_the_end():
    g = ChannelGuard([PHONE])
    first = g.feed("Hello there. " + "x" * 80)
    assert first.startswith("Hello there.") and len(first) > 20


def test_phone_shaped_string_redacted_unless_shared_phone():
    shared = Channel("phone", "Phone", "+44 20 7946 0958", True)
    g = ChannelGuard([shared])
    out = run(g, ["Office +44 20 7946 0958 or 555 123 4567 89."])
    assert "+44 20 7946 0958" in out
    assert "555" not in out and HIDDEN in out


def test_normal_numbers_untouched():
    g = ChannelGuard([PHONE])
    text = "He has 4.5 years, worked 2019-2023 on 12 projects, salary 1,200,000."
    assert run(g, [text]) == text and g.redactions == 0


def test_toggling_share_off_is_immediate():
    on = Channel("instagram", "Instagram", "https://instagram.com/jane_private", True)
    assert "jane_private" in run(ChannelGuard([on]), ["@jane_private"])
    off = Channel("instagram", "Instagram", "https://instagram.com/jane_private", False)
    assert "jane_private" not in run(ChannelGuard([off]), ["@jane_private"])


def test_same_value_shared_elsewhere_stays_visible():
    g = ChannelGuard([IG, Channel("instagram", "IG2", IG.value, True)])
    assert "jane_private" in run(g, ["@jane_private"])


def test_shared_url_not_broken_by_nonshared_prefix():
    hidden = Channel("website", "Old", "https://jane.dev", False)
    shown = Channel("website", "New", "https://jane.dev/portfolio", True)
    out = run(ChannelGuard([hidden, shown]), ["See https://jane.dev/portfolio"])
    assert out == "See https://jane.dev/portfolio"


def test_legacy_identity_values_hidden():
    g = ChannelGuard([], extra_hidden=["+91 98765 43210", "old@example.com"])
    out = run(g, ["old@example.com +91 98765 43210"])
    assert "old@" not in out and "98765" not in out


def test_trailing_digits_of_a_streamed_number_do_not_leak():
    g = ChannelGuard([PHONE])
    out = run(g, ["Call 98765", "4321", "0 now"])
    assert out == f"Call {HIDDEN} now"
