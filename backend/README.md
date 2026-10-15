# mebot backend

FastAPI app that streams answers from the owner's chosen LLM provider and stores profile,
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
                 owner-only: /api/admin/* (profile/{section}, llm, sessions, log)
  llm/           provider adapters (openai_compat, anthropic, ollama), registry,
                 service (validate/test/store config); keys encrypted via crypto.py
  crypto.py      Fernet encryption of stored API keys (HKDF from SECRET_KEY)
  prompt.py      persona system prompt
  profile/       structured profile: schemas, section registry, loader, render_profile()
  profile_legacy.py  0005 copy of the old free-text profile into profile_notes
  legacy.py      import of prototype data (used by migration 0002)
migrations/      Alembic (0001 schema, 0002 legacy import, 0003 admin auth,
                 0004 llm configs, 0005 structured profile)
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

## LLM providers

There is no default provider or model: the owner configures one in setup and in
Admin → AI Provider (`/api/admin/llm`). Every provider adapter implements
`stream_chat`, a 1-token `test` and best-effort `list_models` (`mebot/llm/base.py`).
Provider errors are mapped to typed `LLMError`s with the key scrubbed from any
provider message. Tests never hit the network (respx / a fake client in conftest).

For Ollama the backend sends `"think": false` on every call; Gemma's thinking mode
would otherwise leak reasoning into replies. `OLLAMA_HOST` is only the default base
URL offered for the Ollama provider. Optional named CLI model:

    ollama create me-bot -f ../deploy/ollama/Modelfile.example
