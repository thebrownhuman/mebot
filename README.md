# mebot — candidate terminal

A chat bot recruiters can talk to about a candidate. It answers only from the data
you enter in the admin portal, streaming from the AI provider *you* choose (Gemini, OpenAI, Anthropic,
OpenRouter, Groq, a local Ollama or any OpenAI-compatible server) using your own key.

```
backend/    FastAPI + SQLAlchemy + Alembic (SQLite by default)
frontend/   React + Vite + TypeScript, 3D reactive orb
deploy/     docker-compose, example Ollama Modelfile
```

## Configure

All configuration is via environment variables. Copy `.env.example` to `.env` and
edit; you never need to change source code. Key settings: `MODE`, `SECRET_KEY`,
`DATABASE_URL`, `OLLAMA_HOST`, `CORS_ORIGINS`, `SETUP_TOKEN`,
`COOKIE_SECURE`, `TRUST_PROXY`.

## Run bare-metal (development)

    # terminal 1 (only if you'll use the Ollama provider)
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

    ollama serve          # only for the Ollama provider; keep it on the host for GPU
    cd deploy
    docker compose up --build
    # open http://localhost:8080

## First run

On a fresh install every page redirects to `/setup`. Create the admin account
(email + password, at least 10 characters), name your bot and pick its slug, then
you land in the admin panel at `/admin`. Log in later at `/admin/login`; sessions
last 14 days of inactivity and end on "log out".

Until setup is done the chat API (`/api/chat`) and all `/api/admin/*` endpoints
return 503. Upgrading an existing install keeps its profile and conversations; you
just go through setup once.

**Exposed to the internet on first boot?** Whoever opens `/setup` first becomes the
admin. Set `SETUP_TOKEN` in `.env` before starting; the setup form then asks for it.

**Behind HTTPS?** Cookies get the `Secure` flag automatically when the request is
https. If a reverse proxy terminates TLS and talks plain http to mebot, set
`COOKIE_SECURE=true` (and `TRUST_PROXY=true` if mebot is only reachable via that
proxy). Add the public site origin to `CORS_ORIGINS` if it differs from the host
mebot sees.

## Adding your data

Everything the bot knows comes from the admin portal (`/admin`, sidebar on the
left; a menu button on phones). One page per section:

| Page | What goes there |
|---|---|
| Identity | Name, headline, location, what you're open to, summary, public contact, notice period, salary expectation, work authorisation, photo URL, plus your **links** (GitHub, LinkedIn…) |
| Experience | Jobs with start/end months (tick "I currently work here" for the current one), description, highlights, tech |
| Education | Degrees and courses with dates |
| Skills | Name, category, level, optional years |
| Projects | Summary, problem, your role, frontend / backend / infrastructure / data & AI, highlights, tech, repo and live URLs |
| Interests & Hobbies | What you do outside work, so the bot can talk about you as a person |
| FAQ | Exact answers to questions you get often ("Open to relocation?") |
| Avoid topics | Things the bot must never discuss, with an optional polite reply |
| Notes | Anything else. Text from the old single profile box was moved here on upgrade |
| Preview | The exact text the bot receives, with a size estimate (it warns above ~6k tokens) |

Lists can be reordered with the arrow buttons; the order is the order the bot sees.
Deleting an item hides it (soft delete). Two tabs editing the same item: the last
save wins.

## How answers stay grounded

- **Numbers come from the server, not the model.** mebot computes a FACTS block from
  your dates (as of today, UTC) and puts it first in the prompt: total experience
  (overlapping jobs merged, current jobs counted up to this month), current role,
  time per company, years per skill (from the jobs and dated projects whose tech
  lists it, with common aliases like JS/JavaScript and k8s/Kubernetes, or your own
  "years" override), latest education and counts. The model is told to quote these
  and never do date math. See them on Admin → Preview.
- **Internships and freelance.** Identity has two toggles: count internships (off
  by default) and count freelance/contract work (on by default) toward the total.
- **"I don't know" is tracked.** When the profile can't answer, the bot says so
  (offering your public contact if you set one) and ends with a hidden
  `[[UNANSWERED]]` marker. The server strips it from the stream, flags the
  message and logs the question. The dashboard lists the latest ones so you can
  add the answer to your FAQ or profile.
- **Limits.** This is prompt-level grounding: a model can still ignore its rules.
  Run the golden evals against your provider and model to check:

      cd backend
      python -m mebot.evals --bot default

  It uses `evals/sample_profile.yaml` and `evals/golden.yaml` (21 questions:
  years, roles, projects, hobbies, unknowns, off-topic, avoid-topics, a prompt
  injection) and makes real API calls with your key, so it costs a few cents.

## Add your API key

mebot never ships, provides or shares an API key. During setup (step 2 of 3) you
pick a provider, paste **your own** key, choose a model and press **Test**; setup
can't finish until that live test call succeeds. Change it later in
Admin → AI Provider (`/admin/llm`), which tests before saving.

| Provider | Where to get a key | Notes |
|---|---|---|
| Google Gemini | https://aistudio.google.com/apikey | Free tier available. Uses Gemini's OpenAI-compatible endpoint. |
| OpenAI | https://platform.openai.com/api-keys | |
| Anthropic | https://console.anthropic.com/settings/keys | |
| OpenRouter | https://openrouter.ai/keys | One key, many models (`vendor/model` ids). |
| Groq | https://console.groq.com/keys | |
| Ollama | no key | Runs locally; base URL defaults to `OLLAMA_HOST`. Pull a model first (`ollama pull gemma3`). |
| OpenAI-compatible | depends on the server | Any `/chat/completions` API (vLLM, LM Studio, LiteLLM proxy…); enter its base URL, key optional. |

The key is stored encrypted (Fernet, derived from `SECRET_KEY`) and is never sent
back to the browser — the admin page shows only its last 4 characters. If you change
`SECRET_KEY` the stored key can't be decrypted: chat pauses and the admin panel asks
you to re-enter it. When the provider fails (bad key, quota, outage) visitors see a
polite "assistant unavailable" message; the admin panel shows a banner and the access
log records `LLM_ERROR` with the provider and status code (never the key).

Upgrading an install from before this feature: log in, then follow the banner to
Admin → AI Provider; chat returns 503 until a provider is saved.

### Forgot the admin password

There is no web reset. On the server:

    cd backend
    python -m mebot.cli reset-password --email you@example.com

It prompts for a new password and signs out every session. With Docker:
`docker compose exec backend python -m mebot.cli reset-password --email you@example.com`.

## Protecting your API bill

Every visitor message is a paid call to *your* AI provider, so the public chat is
limited. Change everything in **Admin → Limits** (presets: Strict / Default / Generous).

| Limit | Default | Notes |
|---|---|---|
| Messages per minute per visitor | 10 | In memory; resets when the server restarts. |
| Messages per day per visitor | 100 | Per IP. Many people behind one office IP share it; raise it if that bites. |
| Messages per conversation | 40 | Start a new chat to continue. |
| New chats per hour per visitor | 10 | Stops dodging the per-conversation limit. |
| Total messages per day | 500 | Hard cap for everyone together. |
| Total tokens per day | off | Uses the token counts your provider reports, or characters / 4 when it doesn't (marked "est." in the usage table). |
| Max characters per message | 1000 | Longer messages are refused (`422 MESSAGE_TOO_LONG`). |
| History turns sent to the AI | 12 | Older messages are left out of each request. |

Daily limits reset at 00:00 UTC. A visitor over a limit gets `429` with a friendly
message and `Retry-After`; the chat disables *send* until then. Lowering a cap below
today's usage takes effect immediately.

**Pause.** The big *pause the bot* button stops every chat at once (`503 BOT_PAUSED`,
with your optional message) without calling your provider. The dashboard shows a
banner while paused and when 80% of the daily message cap is used.

**Usage.** Admin → Limits shows the last 7 days: messages, tokens, rate-limited
visitors and blocked leaks, plus the top visitors by hashed IP. IPs in the usage
counters are stored as HMAC-SHA256 with your `SECRET_KEY`, never raw, and counters are
deleted after 7 days.

**Prompt leaks.** The system prompt carries a secret per-bot marker. If a reply
contains it, or repeats a long verbatim piece of the bot's rules, the reply is cut and
replaced with a fixed message (logged as `LEAK_BLOCKED`). Messages that look like
injection attempts ("ignore previous instructions", "developer mode", …) are logged as
`INJECTION_SUSPECTED` and the bot gets an extra reminder for that turn; they are not
blocked.

**Turnstile (optional).** Create a widget in the Cloudflare dashboard, set
`TURNSTILE_SITE_KEY` and `TURNSTILE_SECRET_KEY`, restart, and switch it on in
Admin → Limits. New chats then need a passing check; the script is only loaded when
it is on.

**Setup.** `/api/setup` and its provider probes allow 10 attempts per 15 minutes per
IP, wrong `SETUP_TOKEN`s included.

With several server processes the per-minute windows are per process; the daily caps
are shared through the database.

## Telemetry & registration

Setup has an opt-in checkbox (unchecked by default) to register the install with the
mebot project for security alerts and updates. If ticked it will send your admin
email, site URL and mebot version. For now the choice is only stored
(`bots.registration_consent`); nothing is sent yet.

## Tests

    cd backend  && pytest
    cd frontend && npm run typecheck && npm run build && npm test

## Upgrading from the prototype

If `backend/data/mebot.db` was created by the old single-file `app.py`, the first
start renames its tables to `legacy_*` (kept, not dropped) and copies the profile,
sessions, messages and access log into the new schema under a `default` bot.
Back up the file first if you want a pristine copy.

## Notes
- The frontend never talks to the AI provider directly; all calls go through the
  backend. For Ollama the backend sends `think: false` so model reasoning can't leak.
- Admin auth is server-side: an HttpOnly session cookie, double-submit CSRF token,
  argon2id password hashes and per-IP/per-email login rate limits (in-memory, so
  limits reset on restart and assume one backend process).
- `data/` folders hold the SQLite db and the generated `secret.key`; never commit them.
