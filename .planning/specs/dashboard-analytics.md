# Spec: dashboard-analytics

**Created**: 2026-10-17
**Status**: draft
**Author**: Shivansh Mishra
**Epic**: mebot-open-source (Feature 11)

---

## Problem

The admin dashboard is a mix of leftovers (the old chat + drawers from the prototype, scattered banners and lists added by #5–#10). The owner can't answer simple questions: How many recruiters talked to my bot this week? From which site? What do they ask most? Which chats ended with a contact or an unanswered question? There's no way to browse, search, export or clean up conversations, and no retention policy.

## Goal

A clear Dashboard with key numbers, a 30-day activity chart, top questions, traffic sources and system status; a Conversations page to filter, search, read, export and delete chats with event badges; and a data-retention setting that auto-deletes old conversations. All numbers computed from existing data in the owner's timezone.

## User Stories

- As the **owner**, I open the dashboard and see "This week: 14 chats, 3 unanswered, 2 contacts, mostly from shivansh.dev".
- As the **owner**, I filter conversations to "has contact" in the last 30 days and read each transcript.
- As the **owner**, I search "Kubernetes" to find every chat where a recruiter asked about it.
- As the **owner**, I export last month's conversations as CSV.
- As the **owner**, I set "delete conversations older than 180 days" so I don't keep recruiter data forever.

## Requirements

### Must-have
1. **Timezone:** Alembic 0014 adds `bots.timezone TEXT NOT NULL DEFAULT 'UTC'` (IANA); migration copies `telegram_configs.timezone` when set. Telegram (#7) reads `bots.timezone` from now on (keep its column, stop writing it). Editable on the Account page (browser-zone suggestion). All "today / per day" buckets use it.
2. **Retention:** Alembic 0014 adds `bots.retention_days INT NULL` (default 180 for new bots; NULL = keep forever). Daily job (in the existing lifespan worker loop, plus on startup) **hard-deletes** sessions, messages, access_log rows tied to sessions, and contacts older than the window, and `usage_counters`/outbox per their own rules; logs `RETENTION_PURGED {count}` (counts only). Account page: setting with options 30 / 90 / 180 / 365 / Keep forever + "Delete all conversations now" (type-to-confirm `DELETE`).
3. **Analytics service** `mebot/analytics/` — pure query functions over sessions, messages, access_log (UNANSWERED, PERSONAL_DECLINED, LEAK_BLOCKED, CHANNEL_REDACTED, RATE_LIMITED, WIDGET_OPENED, OWNER_REPLIED), contacts, open_questions, usage_counters. Range `?range=7d|30d|90d` (default 7d) relative to now in bot timezone. Results cached in memory per (bot, range) for 60 s.
   - **KPIs** (current range + previous range for delta): chats (sessions with ≥ 1 visitor message), visitor messages, avg messages per chat, unanswered rate (unanswered replies / bot replies), open questions (current open count), contacts left, owner replies, tokens used (+ estimated flag).
   - **Daily series:** per local day: chats, visitor messages, unanswered.
   - **Top questions:** visitor messages normalised with #7b's normaliser, grouped by exact normalised text then Jaccard ≥ 0.6 (reuse), top 10 with count and an example; personal-declined messages excluded.
   - **Sources:** chats by origin — widget host origin (from WIDGET_OPENED, #8) or "Direct page"; top 10.
   - **Status block:** LLM configured + last test, Telegram linked + outbox health, widget allowed-origin count, paused flag, today's usage vs daily cap (#6).
4. **Conversations API:**
   - `GET /api/admin/conversations?range=&from=&to=&q=&has=unanswered,contact,owner_reply,leak_blocked&origin=&cursor=&limit=25` → `{ items: [{ id, recruiter_name, started_at, last_message_at, messages, origin, flags: [...], preview }], next_cursor }`. Cursor pagination by `(started_at, id)` desc. `q` searches message content (case-insensitive LIKE, min 2 chars, escaped wildcards).
   - `GET /api/admin/conversations/{id}` → session + messages (role, content, created_at, unanswered, from_owner) + events (badges with timestamps) + linked contact.
   - `DELETE /api/admin/conversations/{id}` → hard delete of that session's messages/events/contact (owner-initiated removal of personal data).
   - `GET /api/admin/conversations/export?format=csv|json&…same filters` → streamed download (`Content-Disposition`), one row per message (CSV columns: session_id, started_at, recruiter_name, origin, role, created_at, content, unanswered, from_owner). Max 50k messages per export (422 beyond, suggest narrower range). CSV formula-injection safe (prefix `'` for cells starting with `= + - @`).
   - Replaces old `GET /api/admin/sessions` / `…/messages` (keep as deprecated aliases for one release, documented).
5. **Analytics API:** `GET /api/admin/analytics/overview?range=7d` → `{ kpis, series, top_questions, sources, status }`.
6. **Dashboard UI** (replaces the current dashboard view; old chat/drawers removed — the owner tests the bot via a "Try your bot" link opening `/` or the widget test page):
   - Range switch 7d / 30d / 90d.
   - KPI tiles (value + delta vs previous period with up/down text, not colour only).
   - Activity chart: hand-rolled responsive SVG (no chart library), stacked/paired bars for chats + unanswered per day, accessible (`<title>`, table fallback via "Show as table"), works in light/dark.
   - Top questions list with counts → click opens Conversations filtered by `q`.
   - Sources list with share bars.
   - Status card consolidating existing banners (LLM, Telegram, widget, paused, cap) with links to fix.
   - Open questions summary (#7b) kept.
   - Empty state for a brand-new bot ("No chats yet — share your link or embed the widget" + links).
7. **Conversations UI:** sidebar entry; filter bar (range/custom dates, flags as toggle chips, origin select, search with debounce); list with flag badges and preview; detail panel (side panel on desktop, full page on mobile) showing transcript with badges inline (Unanswered, Owner reply, Leak blocked, Redacted), linked contact card, "Delete conversation" (confirm), "Export" for the current filter (CSV/JSON).
8. **Account page:** timezone, retention, delete-all; links to export.
9. **Docs:** README "Dashboard & your data" — what's stored, retention, export, delete.

### Nice-to-have
- Owner-entered model prices → estimated spend tile.
- Weekly summary via Telegram using the same service.

### Out of scope
- Per-visitor tracking/fingerprinting (never).
- Real-time live view.
- External analytics integrations.

## Data Model

Alembic 0014: `bots.timezone`, `bots.retention_days`; indexes `messages(bot_id, created_at)`, `sessions(bot_id, started_at)`, `access_log(bot_id, event, created_at)` if missing. Retention and owner deletes are **hard deletes** (personal data removal — documented exception to soft delete).

## API Changes

```
GET /api/admin/analytics/overview?range=7d →
{ "range": { "from": "2026-10-11", "to": "2026-10-17", "timezone": "Asia/Kolkata" },
  "kpis": { "chats": { "value": 14, "previous": 9 }, "unanswered_rate": { "value": 0.12, "previous": 0.2 }, ... },
  "series": [{ "date": "2026-10-11", "chats": 2, "visitor_messages": 9, "unanswered": 0 }],
  "top_questions": [{ "question": "What's his tech stack?", "count": 6 }],
  "sources": [{ "origin": "https://shivansh.dev", "chats": 10 }, { "origin": "direct", "chats": 4 }],
  "status": { "llm": { "ok": true }, "telegram": { "linked": true, "dead": 0 }, "widget": { "origins": 2 }, "paused": false,
              "today": { "messages": 31, "cap": 500 } } }
GET /api/admin/conversations?range=30d&has=contact&limit=25 → { "items": [...], "next_cursor": "MjAyNi0xMC0xNlQ…" }
GET /api/admin/conversations/export?format=csv&range=30d → text/csv attachment
PUT /api/admin/account { "timezone": "Asia/Kolkata", "retention_days": 180 } → 200
POST /api/admin/account/delete-conversations { "confirm": "DELETE" } → 200 { "deleted_sessions": 52 }
```

## UI Changes

New Dashboard, Conversations page, Account page settings; old dashboard chat/drawers removed.

## Edge Cases

1. Brand-new bot → zeros + empty states, no division by zero (rates null → "—").
2. DST change inside the range → local-day buckets correct (23/25-hour days).
3. Timezone changed → buckets recomputed; cache invalidated.
4. Retention shortened (365 → 30) → next purge deletes accordingly; shows "will delete N conversations" preview before saving.
5. Retention NULL → nothing purged.
6. Search `q` with `%`/`_` → escaped; 1-char query → 422.
7. Export exceeding 50k messages → 422 with hint.
8. CSV cell starting with `=HYPERLINK(` → neutralised.
9. Conversation deleted while open in another tab → detail 404 → friendly message.
10. Sessions with no visitor messages (opened, never typed) → excluded from chats KPI, still listed with "No messages" filter off by default.
11. Origin missing (direct page) → "Direct page".
12. 100k messages → queries use indexes; overview < 500 ms on SQLite (perf test with seeded data, generous bound).

## Testing Criteria

- Analytics: KPIs + previous-period deltas, series in timezone incl. DST (frozen clock), top questions grouping + personal exclusion, sources, status, caching + invalidation.
- Retention: purge windows, NULL keeps, counts logged, delete-all confirm, contacts included, outbox/counters untouched by this job beyond their own rules.
- Conversations: filters (each flag, origin, dates), search escaping, cursor pagination stability, detail payload, hard delete removes all linked rows, export CSV/JSON content + headers + injection safety + limit.
- Timezone migration copy from telegram_configs; Telegram digest now reads bots.timezone.
- Perf smoke: seeded 100k messages, overview under bound.
- Frontend: KPI tiles + deltas, chart renders + table fallback, range switch, top question click → filtered list, conversations filters/search/pagination/detail/delete/export, account settings + delete-all confirm, empty states.
- `pytest`, `npm run typecheck && npm run build && npm test` green.

## Dependencies

- Features 1–10 (`feature/github-import`).
- No new deps (SVG chart hand-rolled).

---

## Gate 1

- [x] Problem specific · [x] Goal measurable · [x] User stories · [x] Must/nice/out split
- [x] Columns typed with defaults · [x] Indexes listed · [x] Delete strategy stated (hard delete for personal data, documented)
- [x] Endpoints + examples · [x] snake_case JSON · [x] standard error shape
- [x] 12 edge cases · [x] Happy + edge tests · [x] Dependencies listed
