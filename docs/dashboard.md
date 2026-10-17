# Dashboard & your data

**Dashboard** (`/admin`). Pick 7, 30 or 90 days. You get chats, visitor messages,
messages per chat, the share of replies the bot couldn't answer, contacts left, your
own Telegram replies, open questions and tokens used, each compared with the period
before. Below that: a daily activity chart (a table version is one click away), the
most-asked questions, where chats came from (the widget's host site, or "Direct page"),
and one status card for the AI provider, Telegram, the widget, pause and today's cap.
Everything is counted per day in your timezone (set it under **Account**). To try the
bot yourself, use the "Try your bot" link. The numbers are cached for 60 seconds.

**Conversations** (`/admin/conversations`). Filter by period, source and what happened
(unanswered, left contact, you replied, a leak was blocked), search message text
(2+ characters), open a transcript with its events and contact card, and delete a
conversation. **Export CSV / JSON** downloads whatever the filters show (at most 50,000
messages; narrow the period beyond that). In CSV, cells that start with `=`, `+`, `-`
or `@` get a leading `'` so a spreadsheet can't run them as formulas. The old
`GET /api/admin/sessions` endpoints still work but are deprecated; use
`/api/admin/conversations`.

**What is stored.** For each chat: the visitor's name (if given), their messages, the
bot's replies, a log of events (unanswered, blocked, widget origin, contact left) and
any contact details they chose to leave. IP addresses are never stored raw: the activity
log, admin login sessions and the rate-limit counters keep only `HMAC-SHA256(SECRET_KEY, ip)`
(the admin log shows its first 12 characters), and the rate limiter sees the raw IP in memory
only. Activity log rows go when their conversation goes; counters are removed after a week.
Messages are sent to your AI provider to get answers, and nowhere else.

**Retention.** Under **Account** choose to delete conversations older than 30, 90, 180
or 365 days, or keep them forever. New installs start at 180 days; installs upgraded
from an earlier version keep everything until you choose. The purge runs at start-up
and once a day and is a real delete (messages, contacts, activity log), not a soft
delete. Only counts are logged (`RETENTION_PURGED`). Shortening the window shows how
many conversations it will remove before you save.

**Deleting.** Delete one conversation from its transcript, or everything with
**Delete all conversations now** (type `DELETE` to confirm). Both are permanent.
