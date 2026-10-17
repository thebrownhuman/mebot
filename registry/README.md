# mebot registry

A small service the mebot maintainer runs at `https://registry.shivanshmishra.in`.
It receives:

- **heartbeats**: anonymous, about daily, from every mebot install (unless `TELEMETRY=off`);
- **registrations**: only from owners who opted in (e-mail + site URL);
- and serves **release info**: the latest version and security advisories.

It pings the maintainer on Telegram for each new registration and sends a weekly summary.
What is stored is spelled out in [PRIVACY.md](PRIVACY.md). It is separate from the mebot
backend and shares no code with it.

## API

| Method and path | Auth | Purpose |
|---|---|---|
| `POST /v1/heartbeat` | signed | `{install_id, public_key, version, mode}` → 204 |
| `POST /v1/register` | signed | `{install_id, public_key, version, email, site_url, bot_name?}` → 201 (new) / 200 |
| `DELETE /v1/register` | signed | deletes the registration → 204 |
| `GET /v1/latest` | none | `{latest, min_supported, released_at, notes_url, advisories[]}` |
| `GET /v1/stats` | `Authorization: Bearer $REGISTRY_ADMIN_TOKEN` | active installs, versions, registrations |
| `GET /healthz` | none | `{"ok": true}` |

Signed requests carry `X-Mebot-Install`, `X-Mebot-Timestamp` (Unix seconds) and
`X-Mebot-Signature` (base64 Ed25519 over `METHOD\npath\ntimestamp\nsha256hex(body)`).
Timestamps more than 5 minutes off and replayed signatures (10-minute cache) are refused,
and the first public key seen for an `install_id` is pinned. `tests/vectors.json` holds
known-good signatures; mebot's tests check the same file.

Errors use `{"error": {"code", "message", "status"}}`.

## Limits

Per client IP: heartbeat 10/hour, register 5/hour, delete 5/hour; bodies are capped at
4 KB; unknown JSON fields are refused; more than 20 new install ids from one address per
day are throttled. Set `REGISTRY_BLOCKLIST` to refuse emails or domains. Limits are held
in memory (one process), so a restart resets them. Installs unseen for 180 days are purged.

## Configuration

All through environment variables (see `.env.example`):

| Variable | Meaning |
|---|---|
| `REGISTRY_ADMIN_TOKEN` | Bearer token for `/v1/stats`; empty disables it |
| `REGISTRY_TELEGRAM_BOT_TOKEN`, `REGISTRY_TELEGRAM_CHAT_ID` | maintainer notifications; empty = none |
| `REGISTRY_TIMEZONE` | zone for the Monday 09:00 summary (default `Asia/Kolkata`) |
| `REGISTRY_BLOCKLIST` | comma-separated emails or domains |
| `REGISTRY_TRUST_PROXY` | `1` behind a proxy/tunnel: take the client IP from `X-Forwarded-For` |
| `REGISTRY_DATA_DIR`, `REGISTRY_RELEASES` | paths (the Docker image sets them) |

## Publishing a release or an advisory

Edit `releases.json` (it is mounted into the container and hot-reloaded; no restart).
A syntactically broken edit is ignored and the previous version keeps being served.

```json
{
  "latest": "0.10.1",
  "min_supported": "0.8.0",
  "released_at": "2026-10-20",
  "notes_url": "https://github.com/…/releases/tag/v0.10.1",
  "advisories": [
    {
      "id": "MEBOT-2026-001",
      "severity": "high",
      "affected": "<0.10.1",
      "title": "Short description",
      "url": "https://…"
    }
  ]
}
```

`affected` is a comparison against the install's version, such as `<0.10.1` or
`>=0.9.0,<0.10.1`. Installs show a red, non-dismissible banner while one matches.

## Deploy on the homelab

Needs Docker with Compose. These steps assume the box already publishes subdomains the
way the Mealie one does (a tunnel or a reverse proxy); adapt the last step to yours.

1. Copy the `registry/` folder to the server and `cd` into it.
2. `cp .env.example .env` and fill it in: `REGISTRY_ADMIN_TOKEN`
   (`python -c "import secrets; print(secrets.token_urlsafe(32))"`), the Telegram bot token
   and your chat id. Edit `releases.json` if needed.
3. `docker compose up -d --build`. The service listens on `127.0.0.1:8100`.
   Check it: `curl http://127.0.0.1:8100/healthz` and `curl http://127.0.0.1:8100/v1/latest`.
4. Publish `registry.shivanshmishra.in` to `http://127.0.0.1:8100`:
   - **Cloudflare Tunnel:** add a public hostname `registry.shivanshmishra.in` →
     `http://localhost:8100` to the tunnel (HTTPS is handled by Cloudflare), or
   - **Reverse proxy** (Caddy): `registry.shivanshmishra.in { reverse_proxy 127.0.0.1:8100 }`
     (nginx: `proxy_pass http://127.0.0.1:8100;` plus `proxy_set_header X-Forwarded-For $remote_addr;`).
   Either way, keep `REGISTRY_TRUST_PROXY=1` and make sure only the proxy can reach port 8100
   (the compose file binds it to localhost for that reason). Your proxy must set
   `X-Forwarded-For` to the real client address and overwrite any value the client sent.
5. In Telegram, message your bot `/stats` from the configured chat to confirm it answers.
6. Optional: `curl -H "Authorization: Bearer $REGISTRY_ADMIN_TOKEN" https://registry.shivanshmishra.in/v1/stats`.

### Backups and upgrades

State is one SQLite file: back up `registry/data/` (`registry.db`, plus `-wal`/`-shm` while
running; `sqlite3 data/registry.db ".backup backup.db"` takes a consistent copy).
Losing it only forgets who registered; installs register again when their owner next
changes something, and heartbeats rebuild the active-install counts within a day.

Upgrade with `git pull && docker compose up -d --build`.

## Development

    cd registry
    python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt   # Linux/macOS: .venv/bin/pip
    .venv/Scripts/python -m pytest

Run it locally: `REGISTRY_WORKERS=0 uvicorn app.main:app --port 8100 --no-access-log`
(`REGISTRY_WORKERS=0` turns off the Telegram worker and purge loop).
