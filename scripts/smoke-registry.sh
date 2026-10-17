#!/usr/bin/env bash
# Smoke-test a built registry image:  scripts/smoke-registry.sh mebot-registry:ci
set -euo pipefail

IMAGE="${1:?usage: smoke-registry.sh IMAGE}"
NAME="registry-smoke-$$"
PORT="${SMOKE_PORT:-18100}"
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT

docker run -d --name "$NAME" -p "$PORT:8100" "$IMAGE" >/dev/null
for _ in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
        [ "$(docker run --rm --entrypoint id "$IMAGE" -u)" = "10001" ] || { echo "not uid 10001"; exit 1; }
        echo "registry smoke OK"
        exit 0
    fi
    sleep 2
done
docker logs "$NAME" | tail -n 40
echo "SMOKE FAIL: registry /healthz never answered" >&2
exit 1
