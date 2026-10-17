#!/bin/sh
# Container start: check /data, run migrations, start one uvicorn process.
set -eu

DATA_DIR="${DATA_DIR:-/data}"

if ! mkdir -p "$DATA_DIR" 2>/dev/null || ! touch "$DATA_DIR/.write-test" 2>/dev/null; then
    echo "mebot: $DATA_DIR is not writable by uid $(id -u)." >&2
    echo "mebot: on the host run: sudo chown -R 10001:10001 <the directory mounted at $DATA_DIR>" >&2
    echo "mebot: and make sure the volume is not mounted read-only." >&2
    exit 1
fi
rm -f "$DATA_DIR/.write-test"

# Background jobs (Telegram, telemetry, retention) and in-memory rate limits assume ONE
# process. Scale up the machine, not the worker count.
if [ "${WEB_CONCURRENCY:-1}" != "1" ]; then
    echo "mebot: WARNING: WEB_CONCURRENCY=${WEB_CONCURRENCY} ignored; mebot runs a single worker." >&2
fi

cd /app/backend
alembic upgrade head

# --no-access-log: uvicorn's access log would print every visitor IP, which mebot only
# stores hashed. --proxy-headers only takes effect for TRUST_PROXY setups (FORWARDED_ALLOW_IPS).
exec uvicorn mebot.main:app --host 0.0.0.0 --port 8000 --workers 1 \
    --proxy-headers --no-access-log "$@"
