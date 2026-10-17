# Spec: install-registry

**Created**: 2026-10-17
**Status**: draft
**Author**: Shivansh Mishra
**Epic**: mebot-open-source (Feature 12)

---

## Problem

The maintainer (Shivansh) wants to know when someone starts using mebot in real life — with their email and site if they agree — and roughly how many installs are alive. Self-hosters want security alerts and to know when an update is out. Setup (#2) already asks for registration consent and stores it, but nothing is sent and there is nowhere to send it.

## Goal

1. A small, separate **registry service** (`registry/`) the maintainer runs on their homelab at `https://registry.shivanshmishra.in`: receives opt-in registrations, anonymous heartbeats and unregister requests, pings the **maintainer's Telegram** on every new registration, serves the latest version + security advisories.
2. In mebot: consented installs register once; all installs (unless `TELEMETRY=off`) send an anonymous daily heartbeat; admin shows an "Update available" / security banner; owners can change consent or unregister any time. Everything documented and visible.

## User Stories

- As the **maintainer**, I get a Telegram message "🆕 mebot install — priya@acme.dev · https://priya.dev · v0.9.0" when someone opts in.
- As the **maintainer**, I can see "312 active installs this week (v0.9: 280, v0.8: 32)" without collecting anyone's personal data.
- As a **self-hoster**, I see "mebot 0.10.1 is available — security fix" in my admin panel.
- As a **privacy-minded self-hoster**, I set `TELEMETRY=off` and nothing ever leaves my server; or I untick consent and my registration is deleted.

## Requirements

### Part A — Registry service (`registry/`, separate app)
1. **Stack:** FastAPI + SQLite (own DB file, own venv/requirements), single Docker image + `docker-compose.yml` (port 8100, volume `./data`). Deploy notes for the homelab (same reverse-proxy/tunnel approach as the existing Mealie subdomain), `/healthz`. No dependency on the mebot backend package.
2. **Install identity:** each mebot install generates an **Ed25519 keypair** on first boot (stored in `data/install.key`, gitignored, 0600). `install_id` = first 16 bytes (hex) of SHA-256 of the public key. Every registry request is signed (`X-Mebot-Install`, `X-Mebot-Timestamp`, `X-Mebot-Signature` over `method\npath\ntimestamp\nsha256(body)`); registry rejects > 5 min skew and replayed signatures (nonce cache 10 min). First contact pins the public key; later requests must match → nobody can spoof or delete someone else's install.
3. **Endpoints:**
   - `POST /v1/heartbeat` `{ install_id, public_key, version, mode }` — anonymous; upserts `installs(install_id, public_key, first_seen, last_seen, version, mode)`. No IP stored (only used transiently for rate limiting).
   - `POST /v1/register` `{ install_id, public_key, version, email, site_url, bot_name? }` — requires prior or same-request key pin; validates email + http(s) URL; stores in `registrations` (one per install, update on re-register); on **first** registration (or email/site change) enqueues a maintainer Telegram ping.
   - `DELETE /v1/register` (signed) — deletes the registration row (hard delete); heartbeat row remains anonymous.
   - `GET /v1/latest` (public) → `{ latest: "0.10.1", min_supported: "0.8.0", released_at, notes_url, advisories: [{ id, severity, affected: "<0.10.1", title, url }] }` — served from a maintainer-edited `releases.json` file (hot-reloaded).
   - `GET /v1/stats` (maintainer only, `Authorization: Bearer REGISTRY_ADMIN_TOKEN`) → active installs (last_seen ≤ 7 days / 30 days), by version, by mode, registrations count.
4. **Maintainer Telegram:** env `REGISTRY_TELEGRAM_BOT_TOKEN`, `REGISTRY_TELEGRAM_CHAT_ID`; DB-backed outbox with retries (simple version of #7's: pending/sent/dead, backoff, `retry_after`). Messages HTML-escaped. Weekly summary (Monday 09:00 `REGISTRY_TIMEZONE`, default Asia/Kolkata): active installs, new registrations, version split. Command `/stats` from the maintainer chat only.
5. **Abuse protection:** per-IP limits (heartbeat 10/h, register 5/h, delete 5/h), body ≤ 4 KB, strict pydantic schemas, unknown fields rejected; a single IP creating > 20 new install_ids/day is throttled (spam). Optional `REGISTRY_BLOCKLIST` of emails/domains.
6. **Privacy:** heartbeats store no IP, no hostname, no URL; registrations only with consent; `DELETE` honoured immediately; purge installs not seen for 180 days; `PRIVACY.md` in `registry/` describing exactly what is stored.
7. **Tests:** pytest for signatures (valid, wrong key, skew, replay), key pinning, each endpoint, limits, Telegram outbox (respx), stats auth, releases.json reload, purge.

### Part B — mebot app changes
8. **Config:** `TELEMETRY=on|off` (default on; off disables heartbeat, registration and update checks entirely — no network calls), `REGISTRY_URL` (default `https://registry.shivanshmishra.in`). Read once at startup; shown read-only on the Account page.
9. **Install key:** generated on first boot next to `secret.key` (`data/install.key`, 0600, gitignored); `install_id` derived as in req 2. Never shown in full in UI (first 8 chars only).
10. **Registration flow:**
    - Uses existing `bots.registration_consent` (#2). On consent true and `TELEMETRY=on`: register once after setup and again when email/site/version-major changes; site URL = `PUBLIC_URL` (if unset, registration waits and Account page says "Set PUBLIC_URL to register").
    - Email = admin email (#2) unless the owner provides a different "contact email for mebot updates" on the Account page.
    - Consent turned off → `DELETE /v1/register`; local status `unregistered`.
    - Status stored: `telemetry_state` table (single row): `registered_at`, `last_register_error`, `last_heartbeat_at`, `last_check_at`, `latest_version`, `advisories` (JSON), `created_at`, `updated_at`.
11. **Heartbeat:** once per 24 h (± 1 h jitter) from the lifespan worker loop and 5 min after startup; payload only `install_id, public_key, version, mode`. Failures silent (logged at debug), never affect the app.
12. **Update check:** with each heartbeat, `GET /v1/latest`; compare with running version (semver, `mebot.__version__` — add if missing, start `0.9.0`). Admin banner: "Update available: 0.10.1" (dismissible per version) or **red** non-dismissible "Security advisory affects your version" when an advisory matches.
13. **Account page "mebot project" section:** current consent toggle (with the exact text of what is sent), contact email field, registration status (Registered on … / Not registered / Waiting for PUBLIC_URL / Telemetry off by server setting), "What's sent" expandable showing the literal last heartbeat JSON, last check time, link to registry PRIVACY.md.
14. **Setup (#2):** consent checkbox text unchanged; add link "What's sent?" opening the same explanation. `TELEMETRY_DOCS` placeholder link replaced with README anchor `#telemetry` (repo URL still TBD — keep relative link).
15. **Outbound safety:** registry client only calls `REGISTRY_URL` host; 5 s timeout; no redirects followed to other hosts; responses size-capped (64 KB) and schema-validated; advisory URLs shown only if http(s).
16. **Docs:** README "Telemetry & registration" (`#telemetry`): exactly what's sent, when, how to turn off, how to unregister; `registry/README.md` with homelab deploy steps (Docker compose, env vars, reverse proxy/tunnel for `registry.shivanshmishra.in`, backups of `registry/data`).

### Nice-to-have
- Registry web page listing opted-in public sites ("Built with mebot") — only with a separate explicit consent flag.
- Email the maintainer as a fallback channel.

### Out of scope
- Hosted-mode signups (#15) — registry stays for self-hosts.
- Auto-update of mebot.
- Collecting any usage metrics (chat counts etc.).

## Data Model

Registry (own DB): `installs`, `registrations`, `notifications`, `nonces` (ephemeral). mebot (Alembic 0015): `telemetry_state` single row; `bots.update_contact_email TEXT NULL`; `bots.dismissed_update_version TEXT NULL`. snake_case, UTC timestamps; registrations hard-deleted on unregister (privacy).

## API Changes

```
Registry:
POST   /v1/heartbeat  { "install_id": "9f2c…", "public_key": "base64…", "version": "0.9.0", "mode": "single" } → 204
POST   /v1/register   { "install_id": "9f2c…", "public_key": "base64…", "version": "0.9.0", "email": "priya@acme.dev", "site_url": "https://priya.dev" } → 201
DELETE /v1/register   → 204
GET    /v1/latest     → { "latest": "0.10.1", "min_supported": "0.8.0", "advisories": [ ... ] }
GET    /v1/stats      (Bearer) → { "active_7d": 312, "active_30d": 401, "by_version": { "0.9.0": 280 }, "registrations": 57 }

mebot:
GET /api/admin/telemetry → { "telemetry": "on", "registry_url": "https://registry.shivanshmishra.in", "consent": true, "status": "registered",
      "registered_at": "…", "install_id_prefix": "9f2c41aa", "last_heartbeat": { "sent_at": "…", "payload": { … } },
      "update": { "latest": "0.10.1", "current": "0.9.0", "advisory": null } }
PUT /api/admin/telemetry { "consent": false, "update_contact_email": "me@x.dev" } → 200
POST /api/admin/telemetry/dismiss-update { "version": "0.10.1" } → 204
```

## UI Changes

Account page "mebot project" section; admin update/advisory banner; setup "What's sent?" link.

## Edge Cases

1. `TELEMETRY=off` → zero outbound requests (test asserts no httpx calls); Account shows "off by server setting".
2. Registry down / DNS fails → silent, retried next day; app unaffected; no banner errors.
3. Consent on but no `PUBLIC_URL` → status "waiting"; registers once it's set.
4. Consent revoked → DELETE sent; if registry unreachable, retried until success; local status `unregister_pending`.
5. Someone replays a captured register request → nonce/timestamp rejects.
6. Attacker tries to delete another install's registration → signature/key pin mismatch → 401.
7. Install key file deleted → new identity; old registration orphaned (registry purges after 180 days); documented.
8. Malicious/oversized `/v1/latest` response → size cap + schema validation; ignored.
9. Version string not semver (dev build `0.9.0-dev`) → compared by semver rules; dev builds never show "update available" for the same base.
10. Spam registrations → per-IP/day install throttle; blocklist.
11. Maintainer Telegram down → outbox retries; registrations still stored.
12. Owner changes contact email → re-register → maintainer pinged "updated" (not "new").

## Testing Criteria

- Registry: full pytest suite per req 7; Docker build smoke.
- mebot: key generation + permissions + id derivation; signing matches registry verifier (shared test vectors file `registry/tests/vectors.json` copied into mebot tests); TELEMETRY=off no network (respx asserts none); heartbeat schedule + jitter (frozen clock); register on consent/PUBLIC_URL/email change; unregister + retry; update check + banner logic incl. advisories and dismiss; outbound host lock + size cap; Account API auth/CSRF.
- Frontend: Account section states (registered / waiting / off / error), "What's sent" JSON, consent toggle → confirm text, banners (update dismissible, advisory not).
- `pytest` (mebot + registry), `npm run typecheck && npm run build && npm test` green.

## Dependencies

- Features 1–11 (`feature/dashboard-analytics`).
- Python: `cryptography` (already present, Ed25519) for both apps. Registry has its own `requirements.txt` (fastapi, uvicorn, httpx, cryptography, pydantic).

---

## Gate 1

- [x] Problem specific · [x] Goal measurable · [x] User stories · [x] Must/nice/out split
- [x] Tables have id + timestamps · [x] Types defined · [x] Hard delete on unregister stated (privacy)
- [x] Endpoints + examples · [x] snake_case JSON · [x] standard error shape
- [x] 12 edge cases · [x] Happy + edge tests · [x] Dependencies listed
