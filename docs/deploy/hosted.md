# Hosted mode (many owners, one deployment)

`MODE=hosted` turns one mebot deployment into a small platform: people sign up, bring
their own AI key, build their own assistant and embed it. You, the operator, see tenants'
metadata and usage counts, never their keys, profiles or conversations.

Most people want the single-owner setup in the [README](../../README.md). Run hosted mode
only if you mean to operate a service for other people.

## What you need

- A Linux host with Docker, and a domain pointing at it (`bots.example.com`).
- **Postgres.** Hosted mode refuses to start on SQLite. `ALLOW_SQLITE_HOSTED=1` overrides
  that, for local development only.
- An SMTP account for verification and password-reset mail.
- Cloudflare Turnstile keys. Sign-up requires the bot check and fails closed without it.

## Start

```bash
cd deploy/hosted
cp .env.example .env        # DOMAIN, SECRET_KEY, POSTGRES_PASSWORD, SMTP_*, TURNSTILE_*
docker compose up -d
docker compose exec mebot python -m mebot.cli platform-admin create you@example.com
```

Open `https://bots.example.com/platform` and log in as the operator. That account is
separate from tenant accounts and has no bot of its own.

Caddy gets the certificate for `DOMAIN` automatically. mebot is reachable only through
Caddy (`TRUST_PROXY=true` relies on that).

## How tenants work

| | |
|---|---|
| Sign-up | `/signup`: email, password, name and address (slug). Turnstile is required, and sign-ups are rate-limited per hashed IP. |
| `SIGNUP_MODE` | `open` lets anyone sign up. `invite` sends a valid invite code live at once, and a sign-up without a code waits in the operator's **Sign-ups** queue. `closed` lets nobody sign up. |
| Going live | The owner verifies their email, logs in and finishes **Get started** (name plus an AI key, tested before it's saved). Until then the bot is offline. |
| Public page | `https://DOMAIN/b/{slug}`, or `{slug}.HOSTED_DOMAIN` with a wildcard certificate (see the Caddyfile). |
| Embeds | `data-bot="pk_…"`, the bot's public key, so renaming the slug never breaks an embed. |
| Renaming | The old address redirects (301) for 30 days and can't be taken by anyone else meanwhile. |
| Limits | Owners can lower the chat limits but never raise them above `HOSTED_MAX_*`. Imports are capped per day and by file size. |
| Telegram | Each owner links their own bot. Webhook only: polling is disabled in hosted mode. |
| Deletion | The owner deletes their account under **Account**: the bot goes offline at once and every row is erased after 7 days. Owners can download a JSON export first. |

## Operating

- **Tenants**: usage (messages over 7 and 30 days, tokens over 30 days, last active).
  - **Suspend** with a reason: only you see it, and the public gets a neutral "unavailable" page. The owner is logged out.
  - **Unsuspend**, **delete**, **resend verification**.
- **Sign-ups**: approve queued sign-ups. The owner gets an "approved" email.
- **Invites**: create single-use codes, shown once (only a hash is stored), or revoke them.
  The CLI does the same: `python -m mebot.cli invite create --note "for sam"`.
- **Audit log**: every operator action with who, when, which tenant and the reason.
- **Maintainer pings**: set `PLATFORM_TELEGRAM_BOT_TOKEN` and `PLATFORM_TELEGRAM_CHAT_ID`
  to get a Telegram message on each sign-up and suspension. They're best-effort and never block anything.

## Privacy and telemetry

- Tenant API keys are encrypted with `SECRET_KEY`. **Never change it**: every tenant would
  have to re-enter their key.
- IPs are stored only as `HMAC-SHA256(SECRET_KEY, ip)`.
- With `TELEMETRY=on` the platform sends **one** anonymous heartbeat (install id, version,
  mode). Tenants never register or send anything, and they don't see telemetry settings.

## Backups and upgrades

```bash
docker compose exec postgres pg_dump -U mebot mebot | gzip > mebot-$(date +%F).sql.gz
docker compose pull && docker compose up -d     # migrations run on start
```

Keep `.env` (it holds `SECRET_KEY`) with the backups: without it, the stored keys can't be decrypted.
Retention runs daily and applies each tenant's own conversation window. Deleted tenants
are purged on the same run, once their 7-day grace period has passed.
