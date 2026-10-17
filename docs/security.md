# Security model

mebot is a single-owner app that talks to strangers on the internet with your API key. This
page says what it protects, how, and what it doesn't.

## What is stored, and how

| Data | Where | Protection |
|---|---|---|
| AI provider key, Telegram bot token, GitHub token | database | Encrypted (Fernet, key derived from `SECRET_KEY`). Never sent back to the browser; the UI shows the last 4 characters. |
| Admin password | database | argon2id hash. |
| Admin session token | browser cookie (HttpOnly) | Only `sha256(token)` is stored; sessions expire after 14 days idle. |
| Visitor and admin IP addresses | `access_log.ip_hash`, `admin_sessions.ip_hash`, usage counters | `HMAC-SHA256(SECRET_KEY, ip)`, never the raw IP. Upgrading to 0.9.0 rewrites older raw values in place (migration 0016). |
| Profile, chats, contacts visitors left | database | **Plain text.** Anyone with the database file can read them. |
| `secret.key`, `install.key` | data directory | Plain files, owned by the app user in the image. |

`SECRET_KEY` (or the generated `secret.key`) is the root secret: with it and the database an
attacker can decrypt your stored keys. Back up the data directory as a whole and keep the
backup private. Changing `SECRET_KEY` makes stored keys unreadable (you re-enter them) and
changes every IP hash (rate-limit history starts over).

## What reaches whom

- **Your AI provider** gets the system prompt (your shared profile) and the conversation.
- **Telegram** (if linked) gets visitor names, their questions, "couldn't answer" notices and
  contacts they left. Never IPs, your notes, the prompt or keys.
- **The mebot registry** (unless `TELEMETRY=off`) gets an anonymous heartbeat; registration
  is opt-in. See [telemetry](telemetry.md).
- **GitHub** gets requests only when you run a GitHub import.
- Nothing else. uvicorn's access log is off in the image, so raw IPs don't reach container
  logs either.

## Defences in the app

- Admin: server-side sessions, double-submit CSRF token plus an origin check, per-IP and
  per-email login limits, optional `SETUP_TOKEN` for the first boot.
- Public chat: per-visitor and global caps, max message length, a pause switch, optional
  Cloudflare Turnstile ([limits](limits.md)).
- Prompt: grounding rules, a per-bot canary that cuts replies leaking the prompt, injection
  phrases logged, contact channels you don't share never sent to the model and masked in
  output, personal topics declined ([profile](profile.md)).
- Embed: `frame-ancestors` lists only your allowed sites; the app itself can't be framed.
- Container: runs as uid 10001, only `/data` writable, no secrets baked into the image.

## Threat model, briefly

In scope: random visitors abusing the chat (cost, prompt injection, prompt extraction,
fishing for channels you didn't share), drive-by takeover of an unconfigured install,
cross-site attacks on the admin, other sites framing your bot.

Out of scope: anyone with shell or file access to your server or backups, a compromised AI
provider, a model that ignores its instructions in ways the guards don't catch (run the
evals, see [profile](profile.md)), and denial of service beyond the built-in caps (put a CDN
or rate-limiting proxy in front if you expect it).

Found a vulnerability? See [SECURITY.md](../SECURITY.md).
