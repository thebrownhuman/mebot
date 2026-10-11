# Spec: foundation

**Created**: 2026-10-12
**Status**: draft
**Author**: Shivansh Mishra
**Epic**: mebot-open-source (Feature 1)

---

## Problem

The prototype is a single 328-line `app.py` with the owner's name hardcoded in frontend routes, config hardcoded in source, no tenancy column on any table, no migrations and no tests. Nobody else can run it without editing code, and every later epic feature (auth, providers, structured profile, hosted mode) has no clean place to land.

## Goal

Same user-visible behaviour as today (Ollama chat, profile, sessions, log), on a restructured codebase that: is configured only via env, has a `bots` table with `bot_id` scoping on all data, uses versioned migrations, keeps existing `mebot.db` data, and has passing backend + frontend test suites.

## User Stories

- As a **self-hoster**, I configure the app through `.env` (copied from `.env.example`) and never edit source code.
- As the **maintainer**, I add later features (auth, providers, hosted mode) into clear modules with tests, without rewriting the data layer.
- As the **existing owner**, my current profile and past conversations survive the upgrade.

## Requirements

### Must-have
1. Repo layout: `backend/` (from `mebot-app/backend`), `frontend/` (from `mebot-react`), `deploy/` (from `mebot-stack`). Use `git mv` to keep history. Update docker-compose paths and READMEs.
2. Backend package layout:
   ```
   backend/
     mebot/
       __init__.py
       main.py          # create_app() factory, mounts routers
       config.py        # pydantic-settings Settings
       db.py            # SQLAlchemy engine/session, get_db dependency
       models.py        # SQLAlchemy Core/ORM tables
       repos/           # data access, every query scoped by bot_id
       routes/          # health, profile, sessions, chat, log
       llm/ollama.py    # current Ollama streaming, moved as-is
       prompt.py        # build_system_prompt (moved)
     migrations/        # Alembic
     tests/
     alembic.ini
     pyproject.toml or requirements.txt (+ requirements-dev.txt)
   ```
3. Settings via env (pydantic-settings): `MODE` (`single`|`hosted`, default `single`), `SECRET_KEY` (required in hosted; auto-generated + persisted to `data/secret.key` in single if unset), `DATABASE_URL` (default `sqlite:///data/mebot.db`), `TELEMETRY` (`on`|`off`, default `on` — unused until #12), `OLLAMA_HOST`, `OLLAMA_MODEL`, `CORS_ORIGINS` (comma list, default `http://localhost:5173`). `.env.example` at repo root documents all.
4. Schema (Alembic revision 0001):
   - `bots`: `id TEXT PK (uuid4)`, `slug TEXT UNIQUE NOT NULL`, `name TEXT NOT NULL`, `created_at`, `updated_at`, `deleted_at NULL`
   - `profiles`: `id`, `bot_id NOT NULL`, `content TEXT`, `created_at`, `updated_at` (one row per bot; unique index on bot_id)
   - `sessions`: `id`, `bot_id`, `recruiter_name`, `started_at`, `created_at`
   - `messages`: `id`, `bot_id`, `session_id`, `role`, `content`, `created_at`
   - `access_log`: `id`, `bot_id`, `session_id NULL`, `event`, `detail`, `ip`, `created_at`
   - Index on `bot_id` for every table; `(session_id, created_at)` on messages. No FKs (app-level integrity). Timestamps stored UTC.
5. Legacy import: on first run, if old tables (`profile`, `sessions` without `bot_id`, …) exist, migration 0002 creates a default bot (`slug=default`) and copies rows into new tables, converting REAL epoch to UTC datetimes. Idempotent.
6. Single-mode bot resolution: a `get_current_bot` dependency returns the default bot (creates it if missing). Routes never query without `bot_id`.
7. API paths and response shapes stay identical (`/api/health`, `/api/profile`, `/api/session`, `/api/sessions`, `/api/session/{sid}/messages`, `/api/chat`, `/api/log`) so the frontend works unchanged, except where noted.
8. Frontend: remove `/talkaboutshivansh` routes → public chat at `/`, admin at `/admin` (still unauthenticated; #2 adds auth). Remove owner name from any copy. `npm run typecheck` and `npm run build` pass.
9. Tests:
   - Backend pytest: app factory boots against temp SQLite; migrations upgrade from empty DB; legacy import test with fixture old-schema DB; repo scoping test (bot A cannot read bot B sessions); route tests for profile get/put, session create/list, messages; chat route with mocked Ollama stream.
   - Frontend Vitest + Testing Library: setup + one smoke test (App renders chat at `/`).
10. Remove `Modelfile.me-bot` personal content from repo root path (move to `deploy/ollama/Modelfile.example` with placeholder text).

### Nice-to-have
- `ruff` config + `make`/`justfile` with `dev`, `test`, `lint`.
- Structured logging in UTC.

### Out of scope
- Auth / first-run setup (#2)
- Non-Ollama providers, key encryption (#3)
- Structured profile tables / new admin pages (#4)
- Single Docker image, CI, docs site (#13)
- Any UI redesign

## Data Model

See Requirement 4. Naming: snake_case tables/columns, plural table names, UUID text IDs, `TIMESTAMP WITH TIME ZONE` semantics (UTC), soft delete via `deleted_at` on `bots`.

## API Changes

None in shape. Internally every handler resolves `bot` via dependency. Example unchanged:

```
PUT /api/profile
{ "content": "NAME: ..." }  →  { "ok": true }

GET /api/sessions
→ [{ "id": "…", "recruiter_name": null, "started_at": 1760000000.0, "turns": 4 }]
```
`started_at` / `ts` stay epoch floats in responses for frontend compatibility (converted from stored datetimes).

## UI Changes

Routes only: `/` chat, `/admin` admin, `*` → `/`.

## Edge Cases

1. **Fresh install, no DB file** → migrations create schema, default bot auto-created, default profile template served.
2. **Existing prototype DB** (`mebot.db` with old tables) → data copied into new tables under default bot; old tables renamed `legacy_*`, not dropped. Running twice doesn't duplicate.
3. **`SECRET_KEY` unset in single mode** → generated once, persisted in `data/secret.key` (gitignored); restart reuses it. Unset in `hosted` → app refuses to start with clear error.
4. **`data/` dir missing / read-only** → clear startup error, not stack trace.
5. **Ollama down** → `/api/health` reports `ollama:false`; `/api/chat` streams error message as today, no crash.
6. **Session id from another bot** (future hosted) → 404, verified by scoping test.
7. **Empty / whitespace chat message** → 422.

## Testing Criteria

- Happy: boot, get default profile, save profile, start session, chat (mocked), list sessions, read messages, read log — all pass.
- Edge: legacy import (incl. idempotency), cross-bot isolation, missing SECRET_KEY in hosted mode, empty message rejection, Ollama-unreachable path.
- `pytest` green, `npm run typecheck && npm run build && npm test` green.
- Manual: `uvicorn mebot.main:app` + `npm run dev`, chat end-to-end with Ollama still works.

## Dependencies

- Python 3.11+, FastAPI, SQLAlchemy 2, Alembic, pydantic-settings, httpx, pytest, pytest-asyncio
- Node 20+, Vitest, @testing-library/react, jsdom
- No other epic features.

---

## Gate 1

- [x] Problem specific · [x] Goal measurable · [x] User stories · [x] Must/nice/out split
- [x] Tables have id + timestamps · [x] Types defined · [x] Soft delete strategy (bots.deleted_at)
- [x] Endpoints unchanged + examples · [x] snake_case JSON
- [x] 7 edge cases · [x] Happy + edge tests · [x] Dependencies listed
