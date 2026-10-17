#!/usr/bin/env bash
# Smoke-test a built mebot image:  scripts/smoke.sh mebot:ci
set -euo pipefail

IMAGE="${1:?usage: smoke.sh IMAGE}"
NAME="mebot-smoke-$$"
PORT="${SMOKE_PORT:-18080}"
DATA="$(mktemp -d)"
chmod 0777 "$DATA"

cleanup() {
    docker logs "$NAME" >/tmp/mebot-smoke.log 2>&1 || true
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    rm -rf "$DATA" 2>/dev/null || true
}
trap cleanup EXIT
fail() { echo "SMOKE FAIL: $*" >&2; tail -n 40 /tmp/mebot-smoke.log >&2 2>/dev/null || true; exit 1; }

echo "== runs as non-root"
uid="$(docker run --rm --entrypoint id "$IMAGE" -u)"
[ "$uid" = "10001" ] || fail "expected uid 10001, got $uid"

echo "== refuses an unwritable /data"
if docker run --rm --read-only -v "$DATA":/data:ro "$IMAGE" >/tmp/ro.log 2>&1; then
    fail "started with a read-only /data"
fi
grep -q "not writable" /tmp/ro.log || fail "no clear /data error: $(cat /tmp/ro.log)"

echo "== starts and becomes healthy"
docker run -d --name "$NAME" -p "$PORT:8000" -v "$DATA":/data "$IMAGE" >/dev/null
for _ in $(seq 1 60); do
    state="$(docker inspect -f '{{.State.Health.Status}}' "$NAME" 2>/dev/null || echo gone)"
    [ "$state" = "healthy" ] && break
    [ "$state" = "gone" ] && fail "container exited"
    sleep 2
done
[ "$state" = "healthy" ] || fail "not healthy after 120s (state: $state)"

base="http://127.0.0.1:$PORT"
curl -fsS "$base/api/health" | grep -q '"version"' || fail "/api/health has no version"
curl -fsS "$base/api/setup/status" | grep -q '"setup_required":true' || fail "setup not required on a fresh /data"
curl -fsS -o /dev/null "$base/widget/v1.js" || fail "/widget/v1.js"
curl -fsS "$base/admin" | grep -qi "<!doctype html" || fail "SPA fallback /admin"
code="$(curl -s -o /dev/null -w '%{http_code}' "$base/api/does-not-exist")"
[ "$code" = "404" ] || fail "/api 404 swallowed (got $code)"
asset="$(curl -fsS "$base/" | grep -o '/assets/[^"]*\.js' | head -n1)"
[ -n "$asset" ] || fail "no hashed asset referenced from index.html"
curl -fsSI "$base$asset" | grep -qi "cache-control: public, max-age=31536000, immutable" \
    || fail "asset cache headers"
[ -f "$DATA/secret.key" ] || fail "secret.key not written to /data"

echo "smoke OK"
