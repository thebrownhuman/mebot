# mebot

Self-hostable portfolio chatbot: owner adds their own LLM key, bot answers recruiters as the owner's assistant (third person, strictly professional), pings owner on Telegram, embeds on any site. Plan: `.planning/epics/mebot-open-source.md`; one spec per feature in `.planning/specs/`.

## Layout
- `backend/` FastAPI + SQLAlchemy 2 + Alembic, SQLite default. Package `mebot/`, venv `backend/.venv`, migrations `backend/migrations/versions/` (numbered 00NN).
  - `routes/` HTTP (public: chat, sessions, setup, auth, public, widget, contact, health; admin_*: one file per admin area)
  - `profile/` structured profile + `render.py` (prompt knowledge, FACTS) · `prompt.py`/`persona.py` system prompt · `marker.py` + `guard/` stream filters (UNANSWERED/PERSONAL markers, leak, channel redaction)
  - `llm/` provider adapters · `limits/` rate limits · `telegram/` client, poller, outbox · `learning/` open questions + learned facts · `imports/` resume/LinkedIn/GitHub · `analytics/` · `telemetry/` registry client · `widget/`
  - `tests/` pytest; `conftest.py` has FakeLLM; respx for HTTP. No real network in tests.
- `frontend/` React + Vite + TS + Tailwind + Vitest. `src/pages/` (Recruiter, Setup, Login, Admin + `admin/`), `src/embed/` iframe app, `src/widget/` loader script, `src/lib/` API client.
- `registry/` separate FastAPI service (install registry, runs on owner's homelab). Own venv/tests.
- `deploy/` compose + examples.

## Commands
- Backend tests: `cd backend && .venv/Scripts/python -m pytest -q` (full suite ~7–13 min — run relevant files while iterating). Lint: `.venv/Scripts/ruff check mebot tests`.
- Frontend: `cd frontend && npm run typecheck && npm run build && npm test` (includes bundle size check).
- Registry: `cd registry && .venv/Scripts/python -m pytest`.

## Rules
- TDD. Logical commits. Never commit `.db`, `secret.key`, `install.key`, `.env`. Never touch `backend/data/mebot.db` (real data).
- Read only failure output from test/build runs.
- Don't edit `.planning/` unless you're the orchestrator. Don't push or open PRs unless asked.
- Workers: read only the spec you're given + the files it names. Don't read other specs unless the task says so.
