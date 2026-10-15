# Spec: setup-auth

**Created**: 2026-10-15
**Status**: draft
**Author**: Shivansh Mishra
**Epic**: mebot-open-source (Feature 2)

---

## Problem

All admin endpoints (`PUT /api/profile`, `/api/sessions`, `/api/session/{sid}/messages`, `/api/log`) are public. The only "protection" is a browser-side passphrase (`VITE_ADMIN_PASS`) baked into the JS bundle — anyone can read it or call the API directly. A self-hoster also has no guided first run: no way to create an owner account or name their bot without editing files.

## Goal

A fresh install shows a first-run setup screen; after setup, every admin API requires a valid server-side session, the public chat API stays open, and the client-side passphrase is gone.

## User Stories

- As a **self-hoster**, on first visit I'm sent to `/setup`, create my admin email + password, name my bot, choose whether to register my install, and land in the admin panel.
- As the **owner**, I log in at `/admin/login`, stay logged in for days on my device, and log out explicitly.
- As an **attacker/visitor**, I cannot read conversations, logs, or change the profile without logging in, and I can't brute-force the password.

## Requirements

### Must-have
1. **Schema (Alembic 0003):**
   - `admins`: `id TEXT PK uuid`, `email TEXT UNIQUE NOT NULL` (lowercased), `password_hash TEXT NOT NULL`, `created_at`, `updated_at`, `deleted_at NULL`
   - `admin_sessions`: `id TEXT PK` (store **SHA-256 of the token**, never the raw token), `admin_id`, `created_at`, `expires_at`, `last_seen_at`, `ip`, `user_agent`
   - `bot_settings` (or columns on `bots`): `registration_consent BOOLEAN NOT NULL DEFAULT false`, `setup_completed_at NULL`
   - No FKs; index `admin_sessions.admin_id`, `admin_sessions.expires_at`.
   - In single mode, admins are not bot-scoped (one admin owns the default bot). Add `bot_id` to `admins` anyway (nullable) for hosted mode later.
2. **Setup flow:**
   - `GET /api/setup/status` → `{ "setup_required": true|false }` (public).
   - `POST /api/setup` (public, only works while no admin exists; otherwise 409) with `{ "email", "password", "bot_name", "bot_slug", "registration_consent" }` → creates admin, updates default bot name/slug, stores consent, sets `setup_completed_at`, logs the admin in (sets cookie). Single transaction.
   - Race: two concurrent setup calls → exactly one succeeds (unique constraint / transaction), other gets 409.
   - Optional `SETUP_TOKEN` env: if set, `POST /api/setup` requires `{ "setup_token" }` matching it. Documented as recommended for internet-exposed first boots.
3. **Passwords:** argon2id via `argon2-cffi`. Min length 10, max 256. No other composition rules. Constant-time verify. Email validated by `pydantic.EmailStr`.
4. **Login / logout / me:**
   - `POST /api/auth/login` `{ "email", "password" }` → 204 + cookie; wrong creds → 401 generic `"Invalid email or password"` (same for unknown email; still run a dummy hash to equalise timing).
   - `POST /api/auth/logout` → deletes session row, clears cookie, 204.
   - `GET /api/auth/me` → `{ "email", "bot_name", "bot_slug" }` or 401.
   - `POST /api/auth/password` (authed) `{ "current_password", "new_password" }` → changes hash, revokes all other sessions.
5. **Session cookie:** name `mebot_session`, 32-byte random token (`secrets.token_urlsafe`), `HttpOnly`, `SameSite=Lax`, `Secure` when request is HTTPS or `COOKIE_SECURE=true`, `Path=/`, 14-day sliding expiry (refresh `expires_at` when < 7 days left). Expired rows purged on startup and opportunistically.
6. **CSRF:** all state-changing admin requests (POST/PUT/PATCH/DELETE under `/api/admin`, `/api/auth/*` except login, `/api/setup`) require either a matching `Origin`/`Referer` against allowed origins (same host + `CORS_ORIGINS`) **or** an `X-CSRF-Token` header equal to the `mebot_csrf` cookie (double-submit; non-HttpOnly cookie set at login). Implement double-submit; Origin check as additional defence.
7. **Login brute-force limit:** max 5 failed attempts per IP per 15 min and 10 per email per 15 min → 429 with `Retry-After`. In-memory store is acceptable (single process) behind an interface so #6 can swap it.
8. **Route split:**
   - Public (no auth): `GET /api/health`, `POST /api/session`, `POST /api/chat`, `GET /api/setup/status`, `POST /api/setup`, auth endpoints.
   - Admin (auth required) moved under `/api/admin/…`: `GET/PUT /api/admin/profile`, `GET /api/admin/sessions`, `GET /api/admin/sessions/{sid}/messages`, `GET /api/admin/log`. Old admin paths return 404 (removed). Response shapes unchanged.
   - `get_current_admin` dependency; 401 JSON `{ "error": { "code": "UNAUTHENTICATED", "message": "Login required", "status": 401 } }`.
   - While setup is required, all `/api/admin/*` and `/api/chat` return 503 `{ "error": { "code": "SETUP_REQUIRED", … } }`.
9. **Frontend:**
   - Remove `VITE_ADMIN_PASS` and all client-side passphrase logic.
   - App boot calls `/api/setup/status`; if required, every route redirects to `/setup`.
   - `/setup` page: email, password (+ confirm), bot name, slug (auto from name, editable, `^[a-z0-9-]{3,40}$`), consent checkbox **unchecked by default** with plain text: "Register this install with the mebot project (sends your email, site URL and version) to get security alerts and updates." Link to README telemetry section.
   - `/admin/login` page; `/admin/*` guarded by `GET /api/auth/me`; logout button in admin.
   - API client: `credentials: "include"`, sends `X-CSRF-Token` from cookie on mutating requests, maps 401 → redirect to login, shows backend `error.message`.
   - Visual style matches existing app (Tailwind, orb theme); all fields labelled; keyboard accessible; loading + error states.
10. **Password reset (self-host):** CLI command `python -m mebot.cli reset-password --email x` prompts for a new password and revokes sessions. No email-based reset.
11. **Docs:** README "First run" section, `SETUP_TOKEN`, `COOKIE_SECURE`, password reset CLI. `.env.example` updated.

### Nice-to-have
- "Sessions" list in account settings (current devices, revoke).
- Show "last login" on admin dashboard.

### Out of scope
- Multiple admins / roles, OAuth/SSO, 2FA, email-based reset (later / hosted mode).
- Sending registration to the registry (#12) — only store consent here.
- Public chat rate limits (#6).
- New admin data pages (#4).

## Data Model

See Requirement 1. snake_case, UUID text ids, UTC timestamps, soft delete on `admins` via `deleted_at`.

## API Changes

```
GET  /api/setup/status            → { "setup_required": true }
POST /api/setup                   { "email": "a@b.com", "password": "…", "bot_name": "Shivansh", "bot_slug": "shivansh", "registration_consent": false, "setup_token": "…?" }
                                  → 201 { "email": "a@b.com", "bot_slug": "shivansh" } + Set-Cookie
POST /api/auth/login              { "email", "password" } → 204 + Set-Cookie | 401 | 429
POST /api/auth/logout             → 204
GET  /api/auth/me                 → { "email", "bot_name", "bot_slug" } | 401
POST /api/auth/password           { "current_password", "new_password" } → 204 | 400 | 401
GET  /api/admin/profile           (was /api/profile)
PUT  /api/admin/profile
GET  /api/admin/sessions          (was /api/sessions)
GET  /api/admin/sessions/{sid}/messages
GET  /api/admin/log               (was /api/log)
```
Errors use the standard `{ "error": { "code", "message", "status", "details?" } }` shape.

## UI Changes

New pages: `/setup`, `/admin/login`. Admin page gets auth guard + logout. Recruiter chat unchanged. Default profile text still served by public chat prompt (not by an endpoint).

## Edge Cases

1. Setup already completed → `POST /api/setup` 409; `/setup` page redirects to `/admin/login`.
2. Two browsers submit setup simultaneously → one 201, one 409; only one admin row.
3. Upgrading an existing install (from foundation) → no admin yet → setup required; existing profile/conversations preserved and visible after setup.
4. Expired / tampered / unknown cookie → 401, cookie cleared.
5. Password change → other sessions revoked, current stays valid.
6. Brute force → 429 after limit; correct password still blocked until window passes.
7. Missing / wrong CSRF token on mutation → 403.
8. Slug invalid or reserved (`admin`, `setup`, `api`, `widget`, `assets`) → 422 with field detail.
9. App behind reverse proxy (HTTPS terminated) → `COOKIE_SECURE=true` documented; trust `X-Forwarded-Proto` only when `TRUST_PROXY=true`.
10. Lost password → CLI reset works offline; no web reset path exists to abuse.

## Testing Criteria

- Backend: setup happy path; setup twice (409); concurrent setup; SETUP_TOKEN required/wrong; login ok/wrong/unknown email (same response); rate limit 429; logout; me; password change revokes other sessions; session expiry & sliding refresh; CSRF missing/wrong → 403; every `/api/admin/*` route 401 without cookie; public routes still open; chat/admin 503 while setup required; old admin paths 404; token stored hashed; CLI reset.
- Frontend (Vitest + Testing Library): redirect to `/setup` when required; setup form validation (password mismatch, slug format, consent unchecked by default); login error shows backend message; admin guard redirects on 401; logout.
- Manual: fresh DB → setup → chat works → admin works → logout → login.
- `pytest`, `npm run typecheck`, `npm run build`, `npm test` all green.

## Dependencies

- Feature 1 (foundation) — branch `feature/foundation`.
- New Python deps: `argon2-cffi`, `email-validator`.

---

## Gate 1

- [x] Problem specific · [x] Goal measurable · [x] User stories · [x] Must/nice/out split
- [x] Tables have id + timestamps · [x] Types defined · [x] Soft delete (admins.deleted_at)
- [x] Endpoints + examples · [x] snake_case JSON · [x] standard error shape
- [x] 10 edge cases · [x] Happy + edge tests · [x] Dependencies listed
