# Protecting your API bill

Every visitor message is a paid call to *your* AI provider, so the public chat is
limited. Change everything in **Admin → Limits** (presets: Strict / Default / Generous).

| Limit | Default | Notes |
|---|---|---|
| Messages per minute per visitor | 10 | In memory; resets when the server restarts. |
| Messages per day per visitor | 100 | Per IP. Many people behind one office IP share it; raise it if that bites. |
| Messages per conversation | 40 | Start a new chat to continue. |
| New chats per hour per visitor | 10 | Stops dodging the per-conversation limit. |
| Total messages per day | 500 | Hard cap for everyone together. |
| Total tokens per day | off | Uses the token counts your provider reports, or characters / 4 when it doesn't (marked "est." in the usage table). |
| Max characters per message | 1000 | Longer messages are refused (`422 MESSAGE_TOO_LONG`). |
| History turns sent to the AI | 12 | Older messages are left out of each request. |

Daily limits reset at 00:00 UTC. A visitor over a limit gets `429` with a friendly
message and `Retry-After`; the chat disables *send* until then. Lowering a cap below
today's usage takes effect immediately.

**Pause.** The big *pause the bot* button stops every chat at once (`503 BOT_PAUSED`,
with your optional message) without calling your provider. The dashboard shows a
banner while paused and when 80% of the daily message cap is used.

**Usage.** Admin → Limits shows the last 7 days: messages, tokens, rate-limited
visitors and blocked leaks, plus the top visitors by hashed IP. IPs in the usage
counters are stored as HMAC-SHA256 with your `SECRET_KEY`, never raw, and counters are
deleted after 7 days.

**Prompt leaks.** The system prompt carries a secret per-bot marker. If a reply
contains it, or repeats a long verbatim piece of the bot's rules, the reply is cut and
replaced with a fixed message (logged as `LEAK_BLOCKED`). Messages that look like
injection attempts ("ignore previous instructions", "developer mode", …) are logged as
`INJECTION_SUSPECTED` and the bot gets an extra reminder for that turn; they are not
blocked.

**Turnstile (optional).** Create a widget in the Cloudflare dashboard, set
`TURNSTILE_SITE_KEY` and `TURNSTILE_SECRET_KEY`, restart, and switch it on in
Admin → Limits. New chats then need a passing check; the script is only loaded when
it is on.

**Setup.** `/api/setup` and its provider probes allow 10 attempts per 15 minutes per
IP, wrong `SETUP_TOKEN`s included.

mebot runs as **one process** (the Docker image starts a single uvicorn worker): the
per-minute windows and login limits live in memory, the daily caps in the database.
