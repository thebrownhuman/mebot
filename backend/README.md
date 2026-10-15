# mebot backend

FastAPI app that streams answers from a local Ollama model and stores profile,
sessions, messages and an access log in a SQL database (SQLite by default).

```
mebot/
  main.py        create_app() factory; `uvicorn mebot.main:app`
  config.py      Settings from env / .env (see ../.env.example)
  cli.py         python -m mebot.cli reset-password --email x
  errors.py      ApiError + standard {"error": {...}} responses
  auth/          argon2 passwords, CSRF, login rate limiter, auth cookies
  db.py          engine, sessions, get_db, programmatic Alembic upgrade
  models.py      tables: bots, profiles, sessions, messages, access_log,
                 admins, admin_sessions
  deps.py        get_current_bot, get_current_admin, require_setup_done
  repos/         data access; every query is scoped by bot_id
  routes/        public: /api/health, session, chat, setup, auth
                 owner-only: /api/admin/* (profile, sessions, log)
  llm/ollama.py  Ollama model discovery + streaming
  prompt.py      persona system prompt + default profile template
  legacy.py      import of prototype data (used by migration 0002)
migrations/      Alembic (0001 schema, 0002 legacy import, 0003 admin auth)
tests/           pytest
```

## Run

    python -m venv .venv
    .venv/Scripts/activate            # or: source .venv/bin/activate
    pip install -r requirements-dev.txt
    uvicorn mebot.main:app --reload --port 8000

Migrations run on startup. To run them by hand: `alembic upgrade head`
(uses `DATABASE_URL`).

## Test / lint

    pytest
    ruff check . && ruff format --check .

## Data model

All timestamps are stored in UTC. API responses keep the prototype's epoch-float
`started_at` / `ts` fields so the frontend is unchanged. Tables have no foreign keys;
integrity is enforced in `repos/`. `bots.deleted_at` is the soft-delete marker.

Inspect the db:

    sqlite3 data/mebot.db "SELECT event, detail, created_at FROM access_log ORDER BY created_at DESC LIMIT 20;"

## Ollama

The backend sends `"think": false` on every call; Gemma 4's thinking mode would
otherwise leak reasoning into replies. It uses `OLLAMA_MODEL` (default `me-bot`)
if installed, else falls back to `gemma4:e2b-it-qat`. Optional named CLI model:

    ollama create me-bot -f ../deploy/ollama/Modelfile.example
