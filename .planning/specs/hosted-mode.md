# Feature 15: Hosted mode (MODE=hosted)

Epic: `.planning/epics/mebot-open-source.md` · Depends on: #1–#14 · Size: L, split into **15a** (tenancy core) and **15b** (platform ops) · Worker: Opus

## Goal

One deployment serves many owners. Each signs up, brings their own LLM key, builds their own bot, and embeds it. `MODE=single` must behave exactly as today (every existing test passes unchanged). Billing is out of scope (#16), but leave a `plan` hook.

## Non-negotiables
- **Tenant isolation is the feature.** No request can read or write another tenant's data. Every tenant table already has `bot_id`; every query must filter on it.
- The platform operator never sees tenant LLM keys or conversation text. Only counts and metadata.
- Owner-brought key only. The platform never supplies an LLM key.

---

## 15a — Tenancy core

### Bot resolution (`deps.get_current_bot`)
- **Admin routes:** the bot comes from the logged-in admin (`admins.bot_id`, required in hosted).
- **Public chat/embed routes:** the bot comes from a slug. Use the path `/b/{slug}/…` for the recruiter page and API. The widget uses `data-bot="<public bot key>"` (an opaque random id, not the slug, so renaming the slug doesn't break embeds).
- Optional subdomain `{slug}.{HOSTED_DOMAIN}` when `HOSTED_DOMAIN` is set. Custom domains are out of scope.
- Unknown or suspended slug: 404 (suspended shows a neutral "unavailable" page, no reason given).
- Single mode: `bots.get_primary()` as today; the slug routes 404.

### Accounts
- Public signup: email + password (argon2, existing). Turnstile required, signup rate-limited per hashed IP, and email verification required before the bot goes live.
- `SIGNUP_MODE=open|invite|closed` (default `invite`). Invite codes are created by the platform admin.
- Mailer: SMTP settings; console mailer in dev/tests. Templates: verify, password reset, and a notice when signup is approved.
- Password reset via a single-use token (hashed, 30 min TTL).
- Global `/setup` is disabled in hosted. After signup, the existing setup wizard runs per tenant (name, LLM key test, profile basics, slug choice).
- Slugs: lowercase `[a-z0-9-]{3,32}`, unique, a reserved list (admin, api, b, www, static, platform…), and changeable (keep the old slug as a 301 redirect for 30 days).
- Account deletion by the owner: soft-delete, bot goes offline immediately, hard purge after 7 days. Data export (JSON zip of profile, facts, conversations) before deletion.

### Isolation enforcement
- Repos: every tenant-table function takes `bot_id` explicitly. Add a test that inspects `mebot.repos` and fails on any query helper over a tenant table that lacks a `bot_id` filter (AST or a SQL-compile check; the worker picks one and documents it).
- **Cross-tenant test suite:** create tenants A and B. For every admin route (enumerate from the app router, so new routes are covered automatically), A's session targeting B's ids gets 404 (not 403, so existence isn't leaked). The public routes for slug A never return B's profile, facts or chunks.
- Retrieval chunks, learned facts, open questions, imports, Telegram, contacts, widget settings, analytics and retention are all scoped per bot (verify, fix any global queries).
- Admin session cookie: unchanged, but sessions bind to `bot_id`. A suspended tenant's sessions are revoked.

### Per-tenant limits
- Platform defaults via env (`HOSTED_DEFAULT_*`) plus hard caps. Owners can lower the #6 limits but never raise them above the caps.
- Upload/import caps per tenant (file size, jobs/day, one concurrent import job).
- `bots.plan` text column (default `free`), unused until #16.

### Telegram in hosted
- Each owner links their own Telegram bot token (existing flow), webhook mode only (polling disabled in hosted). Per-bot webhook path with a secret token header (existing secret). The outbox and digest loops iterate all active bots.

### Migrations
Next free numbers after #14. `bots.slug` (unique, nullable in single), `bots.public_key`, `bots.status` (active/suspended/deleted), `bots.plan`, `admins` email-verified fields, `password_resets`, `invites`, `slug_redirects`. No FKs, TEXT ids, soft delete.

---

## 15b — Platform ops

### Platform admin (operator)
- The operator account is bootstrapped by a CLI: `python -m mebot.cli platform-admin create <email>`. It's a separate role from tenant admins and has no bot. UI at `/platform`.
- Views: tenant list (slug, created, status, plan, messages 7d/30d, token usage, last active), signups queue for invite mode, and invite codes.
- Actions: suspend/unsuspend (with a reason the operator sees, not shown publicly), delete tenant, resend verification. **No** viewing of keys, prompts, profiles or conversations.
- An audit log of operator actions.

### Notifications
- Maintainer Telegram ping on each signup (and on suspension), using `PLATFORM_TELEGRAM_BOT_TOKEN` + `PLATFORM_TELEGRAM_CHAT_ID`. Reuse the existing Telegram client; best-effort, never blocks signup.

### Database
- Hosted **requires Postgres** (`DATABASE_URL=postgresql+psycopg://…`). Startup refuses SQLite when `MODE=hosted`, unless `ALLOW_SQLITE_HOSTED=1` (dev only, with a warning).
- Migrations must run on both dialects. CI: a new job runs the full backend suite on Postgres (GitHub Actions service container). Locally, tests stay SQLite.
- Watch out for: SQLite-only SQL (FTS5 from #14 needs a Postgres path: `tsvector` + GIN, behind the same retrieval interface), JSON columns, case-sensitive LIKE, datetime functions.

### Ops
- Telemetry (#12): hosted installs send one heartbeat for the platform, never per tenant.
- Retention, purge and backup docs for hosted. Compose file `deploy/hosted/` with Postgres + mebot + Caddy (wildcard subdomain optional).
- Health endpoint: unchanged; `/api/health` doesn't list tenants.

---

## Tests
- All existing tests are green in single mode (unchanged behaviour).
- Hosted fixtures: two tenants plus an operator.
- The cross-tenant suite enumerates the routes, so a new route without isolation fails CI.
- Signup: verification, invite/closed modes, Turnstile required, reset token single-use and expired, slug rules and redirect, account deletion + purge.
- Operator can't reach tenant content (the endpoints don't exist; a test asserts the absence).
- The Postgres CI job (15b).
- FakeLLM only; no real SMTP (console/fake mailer), no real Telegram.

## Out of scope
Billing, plans and payments (#16); custom domains; SSO; teams (several admins per bot); per-tenant themes beyond existing widget settings.

## Gate 1 checklist
- [ ] Single mode unchanged (full suite green, no new behaviour)
- [ ] Bot resolved from admin session (admin) and slug/public key (public)
- [ ] Automated cross-tenant test over all routes, 404 on foreign ids
- [ ] Signup with verification, Turnstile, IP-hash rate limit, SIGNUP_MODE
- [ ] Operator panel has no access to keys/content; audit log
- [ ] Per-tenant caps enforced; `plan` column present
- [ ] Telegram webhook-only in hosted
- [ ] Postgres required for hosted; CI Postgres job; FTS Postgres path
- [ ] Split: 15a merged and verified before 15b starts
