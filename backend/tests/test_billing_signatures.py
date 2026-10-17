"""Webhook signature vectors (computed independently once, pinned here)."""

import pytest

from mebot.billing import signatures as sig

RZP_SECRET = "rzp_whsec_test"
RZP_BODY = b'{"event":"subscription.charged","id":1}'
RZP_SIG = "13a44970e4bdd1e66e73bd4c1ad130bc60d6a0058a2bd12d94033221ddab1f3a"

ST_SECRET = "whsec_test_vector"
ST_BODY = b'{"id":"evt_1","type":"invoice.paid"}'
ST_T = 1760000000
ST_V1 = "6722397d76828ac4b73ba4c8c3be09d4273414d479a2cdf6386c66dfa35e6fe1"


def test_razorpay_valid():
    assert sig.razorpay_valid(RZP_SECRET, RZP_BODY, RZP_SIG)


@pytest.mark.parametrize(
    "secret,body,header",
    [
        (RZP_SECRET, RZP_BODY.replace(b"1", b"2"), RZP_SIG),  # tampered body
        ("wrong", RZP_BODY, RZP_SIG),  # wrong secret
        (RZP_SECRET, RZP_BODY, RZP_SIG[:-1] + "0"),  # tampered signature
        (RZP_SECRET, RZP_BODY, None),
        (RZP_SECRET, RZP_BODY, ""),
        (RZP_SECRET, RZP_BODY, "zz" * 32),
    ],
)
def test_razorpay_invalid(secret, body, header):
    assert not sig.razorpay_valid(secret, body, header)


def test_stripe_valid_within_tolerance():
    header = f"t={ST_T},v1={ST_V1}"
    assert sig.stripe_valid(ST_SECRET, ST_BODY, header, now=ST_T + 299)
    assert sig.stripe_valid(ST_SECRET, ST_BODY, header, now=ST_T - 299)
    # Several v1 values (secret rotation): any match passes.
    assert sig.stripe_valid(ST_SECRET, ST_BODY, f"t={ST_T},v1={'0' * 64},v1={ST_V1}", now=ST_T)


@pytest.mark.parametrize(
    "secret,body,header,now",
    [
        (ST_SECRET, ST_BODY + b" ", f"t={ST_T},v1={ST_V1}", ST_T),  # tampered
        ("whsec_other", ST_BODY, f"t={ST_T},v1={ST_V1}", ST_T),  # wrong secret
        (ST_SECRET, ST_BODY, f"t={ST_T},v1={ST_V1}", ST_T + 301),  # stale
        (ST_SECRET, ST_BODY, f"t={ST_T},v1={ST_V1}", ST_T - 301),  # from the future
        (ST_SECRET, ST_BODY, f"t={ST_T + 1},v1={ST_V1}", ST_T),  # timestamp swapped
        (ST_SECRET, ST_BODY, f"t={ST_T},v0={ST_V1}", ST_T),  # no v1
        (ST_SECRET, ST_BODY, f"v1={ST_V1}", ST_T),  # no t
        (ST_SECRET, ST_BODY, "garbage", ST_T),
        (ST_SECRET, ST_BODY, None, ST_T),
        (ST_SECRET, ST_BODY, f"t=abc,v1={ST_V1}", ST_T),
    ],
)
def test_stripe_invalid(secret, body, header, now):
    assert not sig.stripe_valid(secret, body, header, now=now)
