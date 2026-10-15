# Spec: telegram

**Created**: 2026-10-16
**Status**: draft
**Author**: Shivansh Mishra
**Epic**: mebot-open-source (Feature 7)

---

## Problem

The owner has no idea when a recruiter is talking to their bot, what they ask, or which questions went unanswered — they only see it if they open the admin panel. Recruiters who want to follow up have no way to leave contact details. The core promise of mebot is "your bot talks to recruiters and pings you on Telegram".

## Goal

Owner connects their own Telegram bot in under 2 minutes without looking up chat IDs. They get real-time pings for new chats, unanswered questions and contact requests, plus a daily digest. They can reply to an unanswered question from Telegram and the answer appears in the recruiter's open chat and can be saved to the FAQ. They can pause/resume the bot from Telegram.

## User Stories

- As the **owner**, I paste my BotFather token, click "Connect", tap the link, press Start in Telegram, and I'm linked.
- As the **owner**, I get "🟢 New chat — Priya (Acme)" when a recruiter starts talking.
- As the **owner**, I get "❓ Unanswered: What's your expected CTC?", reply in Telegram, and the recruiter sees my answer in their chat; I tap "Save to FAQ" so the bot knows next time.
- As a **recruiter**, I click "Leave my contact", enter name/email/company/note, and the owner is notified immediately.
- As the **owner**, I send `/pause` from my phone when something's wrong.

## Requirements

### Must-have
1. **Schema (Alembic 0008):**
   - `telegram_configs` (one per bot): `id`, `bot_id` unique, `bot_token_encrypted` (Fernet/HKDF as #3, info=`mebot-telegram`), `bot_token_last4`, `bot_username`, `chat_id TEXT NULL`, `link_code_hash TEXT NULL`, `link_code_expires_at NULL`, `enabled BOOLEAN DEFAULT true`, `mode TEXT DEFAULT 'polling'` (`polling`|`webhook`), `webhook_secret TEXT NULL`, `last_update_id BIGINT NULL`, event toggles: `notify_new_session DEFAULT true`, `notify_every_question DEFAULT false`, `notify_unanswered DEFAULT true`, `notify_contact DEFAULT true`, `notify_limits DEFAULT true` (paused / ≥80% cap / leak blocked), `daily_digest DEFAULT true`, `digest_hour INT DEFAULT 21`, `timezone TEXT DEFAULT 'UTC'` (IANA), `last_digest_date NULL`, `created_at`, `updated_at`.
   - `notifications` (outbox): `id`, `bot_id`, `kind`, `payload TEXT` (JSON), `status` (`pending`|`sent`|`failed`|`dead`), `attempts INT`, `next_attempt_at`, `telegram_message_id BIGINT NULL`, `session_id NULL`, `ref_message_id NULL` (the unanswered message), `last_error TEXT NULL`, `created_at`, `updated_at`. Index `(status, next_attempt_at)`.
   - `contacts`: `id`, `bot_id`, `session_id NULL`, `name`, `email`, `company NULL`, `role NULL`, `note NULL`, `created_at`, `deleted_at NULL`.
   - `messages.from_owner BOOLEAN DEFAULT false`.
2. **Telegram client** `mebot/telegram/client.py` (httpx, `https://api.telegram.org/bot<token>/…`): `getMe`, `sendMessage` (parse_mode HTML, inline keyboards, `reply_markup.force_reply`), `answerCallbackQuery`, `editMessageReplyMarkup`, `getUpdates` (long-poll 25s), `setWebhook`/`deleteWebhook`. Token never logged; errors scrubbed (reuse #3 scrubber).
3. **Linking flow (no manual chat id):**
   - `PUT /api/admin/telegram` `{ bot_token }` → validates via `getMe`, stores encrypted, returns `bot_username`.
   - `POST /api/admin/telegram/link` → creates one-time code (random 16 chars, stored hashed, 10 min expiry), returns `{ "deep_link": "https://t.me/<bot_username>?start=<code>" }`.
   - Polling/webhook receives `/start <code>` → if valid and unexpired, saves `chat_id`, clears code, replies "✅ Linked to <bot name>". Admin UI polls `GET /api/admin/telegram` until `linked: true`.
   - `POST /api/admin/telegram/test` → sends test message. `DELETE /api/admin/telegram` → unlinks + forgets token.
   - Updates from any chat other than the linked `chat_id` are ignored (except a valid `/start <code>`), logged `TELEGRAM_FOREIGN_CHAT` once per chat/hour.
4. **Receiving updates:**
   - Default **long polling** background task (FastAPI lifespan), only when token configured and `mode=polling`; persists `last_update_id`; backoff on errors (1s→60s); stops cleanly on shutdown; one poller per bot (lock so `--reload`/multi-start doesn't double-poll — use a DB lease row with heartbeat).
   - Optional **webhook** when `PUBLIC_URL` env set and owner picks it: `POST /api/telegram/webhook/{bot_id}` verified by `X-Telegram-Bot-Api-Secret-Token` == `webhook_secret` (constant-time); otherwise 403.
5. **Outbox sender:** background task sends `pending` notifications in order; respects Telegram limits (≤1 msg/s per chat, honour `retry_after` on 429); retries with exponential backoff up to 6 attempts → `dead`; survives restarts (DB-backed). Notifications created inside the same transaction as the event that causes them.
6. **Events → messages** (HTML-escaped visitor text; truncated 800 chars; never include IP, profile notes or system prompt):
   - `new_session`: "🟢 New chat — {recruiter_name or 'Anonymous'}" + time (owner timezone).
   - `every_question` (off by default): "💬 {name}: {question}".
   - `unanswered`: "❓ Unanswered from {name}:\n{question}" with inline buttons **Reply** and **Open chat** (admin URL if `PUBLIC_URL` set).
   - `contact`: "📇 Contact left — {name}, {email}, {company}, {role}\n{note}".
   - `limits`: bot paused/resumed, ≥80% of daily cap (once per day), leak blocked (max 1/hour).
   - `daily_digest` at `digest_hour` in `timezone`: chats, messages, unanswered count, contacts, top 3 questions; skipped if zero activity; sent once per local date.
7. **Reply-back loop:**
   - Owner taps **Reply** → bot sends a `force_reply` prompt "Your answer to: …"; or owner directly replies to the unanswered message. Either way, map `reply_to_message.message_id` → notification → `session_id` + question.
   - Backend stores the owner's text as an assistant message with `from_owner=true` in that session, logs `OWNER_REPLIED`, and replies in Telegram "✅ Sent to {name}" with button **Save to FAQ**.
   - **Save to FAQ** callback → creates `faqs` row (question = original visitor question, answer = owner text); button edited to "Saved ✓". Idempotent on repeated taps.
   - Recruiter side: `GET /api/session/{sid}/updates?after=<iso>` (public, session-bound, rate-limited 20/min) returns new `from_owner` messages; chat UI polls every 5s while tab is visible (stops when hidden / after 30 min idle), shows them as "{owner first name} replied:" with distinct styling.
   - If the session has gone idle, the reply is still stored and visible if the recruiter returns (session id kept in localStorage).
8. **Telegram commands** (linked chat only): `/status` (paused?, today's chats/messages, cap usage), `/pause`, `/resume`, `/today` (same as digest for today so far), `/help`. Set via `setMyCommands` on link.
9. **Contact flow:**
   - Recruiter UI: "Leave my contact" button in chat header + suggested after an unanswered reply; modal with name (required), email (required, validated), company, role, note (≤1000). Consent line: "Your details are shared only with {owner name}."
   - `POST /api/contact` `{ session_id?, name, email, company?, role?, note? }` → 201; rate limit 3/hour/IP via #6 limiter; honeypot field.
   - Admin: `GET /api/admin/contacts` list, `DELETE /api/admin/contacts/{id}` (soft delete). Contacts page in admin sidebar.
10. **Admin UI "Notifications" page:** token field (masked after save, `••••last4`, "How to create a bot with @BotFather" collapsible guide), Connect button → shows deep link + QR code (rendered client-side, no external service) + waiting spinner → "Linked ✓"; event toggles; digest hour + timezone select (browser default suggestion); polling/webhook choice (webhook disabled unless `PUBLIC_URL`); Send test; Unlink; outbox health (last sent, failed/dead count).
11. **Docs:** README "Telegram notifications" with BotFather steps, privacy note (what is sent), webhook vs polling, troubleshooting.

### Nice-to-have
- Reply with `/faq <question> | <answer>` to add FAQ directly.
- Mute notifications for N hours (`/mute 2h`).

### Out of scope
- Other channels (Slack, Discord, email) — later.
- Multiple Telegram recipients.
- Rich media / voice.

## Data Model

Requirement 1. snake_case, UUID ids, UTC timestamps; `contacts.deleted_at` soft delete; outbox rows kept 30 days then purged (operational data).

## API Changes

```
PUT    /api/admin/telegram          { "bot_token": "123:ABC" } → { "bot_username": "shivansh_mebot", "linked": false, "bot_token_last4": "xYz1" }
POST   /api/admin/telegram/link     → { "deep_link": "https://t.me/shivansh_mebot?start=k3J9...", "expires_at": "2026-10-16T10:10:00Z" }
GET    /api/admin/telegram          → { "configured": true, "linked": true, "bot_username": "...", "notify_unanswered": true, ..., "outbox": { "pending": 0, "failed": 0, "dead": 0, "last_sent_at": "..." } }
PATCH  /api/admin/telegram          { "notify_every_question": true, "digest_hour": 21, "timezone": "Asia/Kolkata" }
POST   /api/admin/telegram/test     → 204
DELETE /api/admin/telegram          → 204
POST   /api/telegram/webhook/{bot_id}   (Telegram → us; secret header)
GET    /api/session/{sid}/updates?after=2026-10-16T10:00:00Z → { "messages": [{ "role": "assistant", "from_owner": true, "content": "...", "created_at": "..." }] }
POST   /api/contact                 { "session_id": "...", "name": "Priya", "email": "priya@acme.com", "company": "Acme", "note": "..." } → 201
GET    /api/admin/contacts          → { "items": [...] }
```

## UI Changes

Admin: Notifications page, Contacts page, dashboard "Telegram not linked" hint. Recruiter: contact modal, owner-reply bubbles, polling for updates.

## Edge Cases

1. Invalid bot token → `getMe` 401 → 422 with friendly message; nothing stored.
2. Link code expired / reused / wrong → bot replies "Link expired, generate a new one in admin".
3. Stranger messages the owner's bot → ignored; no data leaked.
4. Telegram down / 429 → outbox retries with backoff, honours `retry_after`; chat unaffected.
5. Owner replies to a non-unanswered message or an old one whose session was deleted → bot replies "Can't match this to a chat".
6. Two app processes / `--reload` → DB lease ensures only one poller; switching to webhook deletes polling and vice versa (`deleteWebhook` before polling).
7. Visitor text containing HTML/`<script>`/Telegram markup → escaped.
8. Owner revokes token in BotFather → poller gets 401 → stops, marks config error, admin banner, logged once.
9. Daily digest across DST change / timezone change → computed in owner's IANA tz; never sent twice for the same local date.
10. Recruiter closed the tab → owner reply stored, shown on return via localStorage session id.
11. Contact spam → 3/hour/IP + honeypot; email validated.
12. Bot paused → `/resume` from Telegram works; notifications still sent.

## Testing Criteria

- Client: request shapes for each method (respx), error scrubbing (token never in logs/errors).
- Linking: code create/hash/expiry/reuse; `/start code` links; foreign chat ignored.
- Poller: processes updates in order, persists offset, backoff, lease prevents double poller, stops on 401.
- Webhook: secret verified (good/bad/missing).
- Outbox: created in same transaction; ordering; per-chat pacing; 429 retry_after; dead after 6; survives restart.
- Events: each kind's text (escaped, truncated, no IP); toggles respected; limits alerts dedup; digest timing with frozen clock + tz + DST; skip when no activity.
- Reply loop: force-reply and direct reply map to session; from_owner message stored; Save to FAQ creates FAQ once; updates endpoint returns only new owner messages for that session; rate limit.
- Commands: /status /pause /resume /today /help; only linked chat.
- Contact: validation, honeypot, rate limit, notification, admin list/delete.
- Frontend: Notifications page flow (save token → connect → linked), toggles, timezone; contact modal; owner reply bubble via polling (fake timers); polling stops when hidden.
- `pytest`, `npm run typecheck && npm run build && npm test` green.

## Dependencies

- Features 1–6 (`feature/chat-hardening`): encryption helpers, limiter, UNANSWERED events, pause.
- Frontend: small QR library (e.g. `qrcode`) if needed — no external QR service.

---

## Gate 1

- [x] Problem specific · [x] Goal measurable · [x] User stories · [x] Must/nice/out split
- [x] Tables have id + timestamps · [x] Types defined · [x] Soft delete (contacts) / purge (outbox) stated
- [x] Endpoints + examples · [x] snake_case JSON · [x] standard error shape
- [x] 12 edge cases · [x] Happy + edge tests · [x] Dependencies listed
