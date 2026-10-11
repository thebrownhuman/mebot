# mebot — candidate terminal

A chat bot recruiters can talk to about a candidate. It answers only from a profile
you write, streaming from a local Ollama model.

```
backend/    FastAPI + SQLAlchemy + Alembic (SQLite by default)
frontend/   React + Vite + TypeScript, 3D reactive orb
deploy/     docker-compose, example Ollama Modelfile
```

## Configure

All configuration is via environment variables. Copy `.env.example` to `.env` and
edit; you never need to change source code. Key settings: `MODE`, `SECRET_KEY`,
`DATABASE_URL`, `OLLAMA_HOST`, `OLLAMA_MODEL`, `CORS_ORIGINS`.

## Run bare-metal (development)

    # terminal 1
    ollama serve

    # terminal 2
    cd backend
    python -m venv .venv && .venv/Scripts/activate   # Windows; use bin/activate elsewhere
    pip install -r requirements-dev.txt
    uvicorn mebot.main:app --reload --port 8000

    # terminal 3
    cd frontend
    npm install
    npm run dev
    # open http://localhost:5173  (admin: http://localhost:5173/admin)

Database migrations run automatically on startup.

## Run with Docker

    ollama serve          # keep Ollama on the host for GPU
    cd deploy
    docker compose up --build
    # open http://localhost:8080

## Tests

    cd backend  && pytest
    cd frontend && npm run typecheck && npm run build && npm test

## Upgrading from the prototype

If `backend/data/mebot.db` was created by the old single-file `app.py`, the first
start renames its tables to `legacy_*` (kept, not dropped) and copies the profile,
sessions, messages and access log into the new schema under a `default` bot.
Back up the file first if you want a pristine copy.

## Notes
- `think: false` is sent to Ollama by the backend on every call; the frontend never
  talks to Ollama directly, so model reasoning cannot leak into the UI.
- `/admin` has only a client-side passphrase (`VITE_ADMIN_PASS`, default `admin`).
  It is not real security; backend auth is planned.
- `data/` folders hold the SQLite db and the generated `secret.key`; never commit them.
