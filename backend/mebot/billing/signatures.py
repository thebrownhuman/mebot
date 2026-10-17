"""Webhook signature checks, done by hand (no provider SDKs). Constant-time compares."""

import hashlib
import hmac
import time

STRIPE_TOLERANCE = 300  # seconds


def _hmac_hex(secret: str, data: bytes) -> str:
    return hmac.new(secret.encode(), data, hashlib.sha256).hexdigest()


def razorpay_valid(secret: str, body: bytes, header: str | None) -> bool:
    """X-Razorpay-Signature = hex HMAC-SHA256(raw body, webhook secret)."""
    if not header:
        return False
    return hmac.compare_digest(_hmac_hex(secret, body), header.strip().lower())


def stripe_valid(
    secret: str, body: bytes, header: str | None, now: float | None = None,
    tolerance: int = STRIPE_TOLERANCE,
) -> bool:  # fmt: skip
    """Stripe-Signature: ``t=<unix>,v1=<hex>[,v1=...]``; v1 = HMAC-SHA256("t.body")."""
    if not header:
        return False
    ts, sigs = None, []
    for part in header.split(","):
        k, _, v = part.strip().partition("=")
        if k == "t":
            ts = v
        elif k == "v1" and v:
            sigs.append(v.lower())
    if ts is None or not ts.isdigit() or not sigs:
        return False
    now = time.time() if now is None else now
    if abs(now - int(ts)) > tolerance:
        return False
    expected = _hmac_hex(secret, ts.encode() + b"." + body)
    return any(hmac.compare_digest(expected, s) for s in sigs)
