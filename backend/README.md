# me-bot — candidate terminal

A full-stack "digital you" recruiters can chat with. Terminal-style frontend with
a reactive 3D orb; FastAPI backend that streams from your local Ollama and stores
everything in SQLite.

```
frontend/index.html      ← open in browser (the UI + Three.js orb)
backend/app.py           ← FastAPI server (proxy + db + sessions + logging)
backend/requirements.txt
backend/data/mebot.db    ← created on first run (profile, sessions, messages, log)
../deploy/ollama/Modelfile.example         ← optional, only for `ollama run me-bot`
```

## Run it (three terminals)

**1 — Ollama** (you already have this):
```
ollama serve
```

**2 — Backend:**
```
cd backend
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

**3 — Frontend:** just open `frontend/index.html` in your browser
(double-click, or serve it — opening the file directly works because the JS calls
the backend at `http://localhost:8000`).

On first load it runs a boot sequence, checks the backend + model, then starts a
session. Click **profile**, paste your real details, hit **save** — the bot answers
only from that. Then type as the recruiter.

## What the orb does
Idles with a slow breathe (teal). Turns amber and spins up while the model is
thinking. Goes bright green and pulses on each streamed token as it "talks", then
settles back to idle. Respects `prefers-reduced-motion`.

## The db
SQLite at `backend/data/mebot.db`. Tables: `profile` (single row), `sessions`,
`messages` (full history), `access_log` (every question + connection, with IP).
Inspect it anytime:
```
sqlite3 backend/data/mebot.db "SELECT event, detail, datetime(ts,'unixepoch','localtime') FROM access_log ORDER BY id DESC LIMIT 20;"
```
Past sessions are browsable in the UI under **sessions**.

## The one hard rule that carried over from Anya
The backend sends `"think": false` to Ollama on every call. Gemma 4's thinking
mode, if on, dumps internal reasoning into the reply — which a recruiter would
see. It can't be baked into the model (Ollama limitation), so the backend does it
per request. If you ever swap the call path, keep `think:false`.

## Optional: named CLI model
```
ollama create me-bot -f ../deploy/ollama/Modelfile.example
ollama run me-bot --think=false
```
The app auto-uses `me-bot` if it exists, else falls back to `gemma4:e2b-it-qat`.
The profile still comes from the db either way.
```
```
