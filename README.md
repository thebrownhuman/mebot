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
| Identity | Name, **pronouns**, headline, location, what you're open to, summary, public contact, notice period, salary expectation, work authorisation, photo URL, the **assistant greeting**, plus your **links** (GitHub, LinkedIn…) |
| Experience | Jobs with start/end months (tick "I currently work here" for the current one), description, highlights, tech |
| Education | Degrees and courses with dates |
| Skills | Name, category, level, optional years |
| Projects | Summary, problem, your role, frontend / backend / infrastructure / data & AI, highlights, tech, repo and live URLs |
| Interests & Hobbies | What you do outside work, so the bot can talk about you as a person |
| FAQ | Exact answers to questions you get often ("Open to relocation?") |
| Avoid topics | Things the bot must never discuss, with an optional polite reply |
| Notes | Anything else. Text from the old single profile box was moved here on upgrade |
| Open questions | Questions the bot couldn't answer, most asked first. Answer once and the bot learns it (see below). The sidebar shows how many are open |
| Memory | Facts the bot learned from you: waiting for your approval, approved, rejected. You can also add a fact directly |
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
  message and files the question under **Open questions**, where you can answer
  it once and the bot learns it (see *How mebot learns*).
- **The bot is your assistant, not you.** It always talks about you in the third
  person ("Shivansh has 4 years of Python…"), uses the pronouns you chose on the
  Identity page (default they/them: it then says your name or "they"), and says it
  is an AI assistant if asked. Recruiters see your **assistant greeting** as the
  first message; it is rendered by the server, not generated, so it costs nothing.
  Placeholders: `{first_name}`, `{name}`, `{pronoun_subj}`, `{pronoun_obj}`.
- **Limits.** This is prompt-level grounding: a model can still ignore its rules.
  Run the golden evals against your provider and model to check:

      cd backend
      python -m mebot.evals --bot default

  It uses `evals/sample_profile.yaml` and `evals/golden.yaml` (29 questions:
  years, roles, projects, hobbies, unknowns, off-topic, avoid-topics, a prompt
  injection, third-person persona, personal questions that must be declined) and makes real API calls with your key, so it costs a few cents.

## How mebot learns

Every professional question the bot can't answer lands in **Admin → Open questions**
(and the sidebar badge counts them). Similar wordings are grouped and counted, so
"What's his notice period?" and "notice period?" become one line, "asked 4×". No AI
call is used for grouping.

1. **You answer** in plain words, in Admin or from Telegram ("Bangalore, open to remote").
2. **One AI call** (with your own provider key, a few cents at most) turns it into a
   clean third-person fact: "Shivansh lives in Bangalore and is open to remote work."
   It may only use what you wrote. mebot then checks that every number, link and
   e-mail in the result appears in your answer; if not, or if the AI fails, the fact
   falls back to your own words, marked **needs review**.
3. **You approve.** Nothing is known to the bot until you press **Approve** (you can
   **Edit** first, or **Reject**, which puts the question back in the inbox).
   - A fact about a single profile field (location, notice period, open to, salary
     expectation, work authorisation) fills that field on the Identity page if it is
     empty. If it already has a value you choose **Replace** or **Keep both**; mebot
     never overwrites it silently.
   - Anything else becomes a **learned fact** (Memory page). The bot gets them in a
     `LEARNED FACTS` section, newest first, as authoritative as the rest of your
     profile. Only the newest 200 are used; Preview warns when you reach that, so move
     old ones into FAQ or projects.
4. **Delete** a learned fact any time and the bot stops saying it (the question reopens).

You are the only teacher: recruiter statements are never learned. Approving twice, or
in Admin and Telegram at once, does nothing the second time.

**In Telegram** (see below), after you reply to a "couldn't answer" notice, **Save to
memory** shows the cleaned fact with **Approve / Edit / Reject**. The daily digest lists
your top 3 open questions with **Answer** buttons, and `/questions` lists the top 5.
You are pinged about a question on its first ask and then at most once a day ("asked 3×").

## What mebot will never discuss

mebot only talks about your work. It always declines, in one polite sentence, questions
about romantic relationships or dating, marital status, sexual orientation, religion or
caste, politics, health or disability, pregnancy or family planning, age or date of
birth, ethnicity or race, finances unrelated to salary, and a home address beyond your
city. This list is built in and can't be edited in this version.

- **Two layers.** A keyword check (English and common Hinglish, whole words only, so
  "Religare" is not "religion") flags the message; the prompt rule makes the model
  decline even indirect phrasings ("is he single?") and end with a hidden `[[PERSONAL]]`
  marker that the server strips.
- **Not logged as unanswered, never sent to you.** A declined question creates no open
  question and no Telegram message (the per-question alert and the digest skip it too).
  The log records `PERSONAL_DECLINED` with the category only, not the question text. The
  chat history itself still stores what the visitor typed, like any message.
- **Your own data doesn't override this.** If you typed something in these categories
  into Notes or an answer, the bot still won't volunteer it, and the cleaning step
  refuses to save personal answers.
- **Still allowed** when you provided them: salary expectation, notice period, work
  authorisation, your city and relocation.
- A false positive on a keyword only adds a hint for the model; it can't hide a
  professional answer. The one side effect: if the keyword matches and the model also
  says it doesn't know, the question is treated as declined instead of opening a question.

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

## Telegram notifications

Get a Telegram message when recruiters chat with your bot, and answer the questions it
couldn't from Telegram — the reply shows up in the recruiter's open chat.

**Set up (about 2 minutes).**

1. In Telegram, open [@BotFather](https://t.me/BotFather), send `/newbot`, pick a name
   and a username ending in `bot`. BotFather replies with a token like `123456789:AAH…`.
2. In Admin → Notifications, paste the token and save. It's checked with Telegram,
   stored encrypted with your `SECRET_KEY`, and only its last 4 characters are shown again.
3. Press **Connect Telegram**, then open the link (or scan the QR code) and press
   **Start**. The page shows "Linked ✓" once Telegram confirms. Only that chat can
   receive notifications or send commands; the link code works once, for 10 minutes.
4. Pick what to be told about, the hour and timezone of the daily digest, and press
   **Send test** to check.

**What gets sent to Telegram.** Only what you need to act on: the recruiter's name
(as they typed it), their questions, the bot's "couldn't answer" notices, contact
details a recruiter chose to leave, limit / leak-guard alerts and daily counts. All
visitor text is HTML-escaped. Personal-topic questions are never sent (see *What mebot
will never discuss*). Never sent: IP addresses, your profile notes, the system
prompt or any API key. Telegram itself stores those messages like any other chat.

**Replying.** On a "couldn't answer" notice, press **Reply** (or reply to the message)
and type your answer. It's added to the recruiter's chat as "{your first name}
replied:" — their chat checks every 5 seconds while the tab is open, and the session
is remembered in their browser, so they see it when they come back. **Save to memory**
turns your answer into a learned fact (cleaned by the AI, then Approve / Edit / Reject;
see *How mebot learns*). Commands in the linked chat: `/status`, `/pause`, `/resume`,
`/today`, `/questions`, `/help`.

**Recruiter contact.** The chat has a "Leave my contact" button (also suggested after
an unanswered question). Entries appear in Admin → Contacts and, if enabled, in
Telegram. A hidden honeypot field and a 3-per-hour limit per visitor keep spam out.

**Polling vs webhook.** Long polling (default) works anywhere, including localhost:
mebot asks Telegram for new messages. A webhook is instant and lighter but needs
`PUBLIC_URL` set to a public https address; switch to it in Admin → Notifications.
Outgoing messages go through a queue (max one per second per chat, retries with
backoff, given up after 6 tries); the page shows pending / retrying / dead counts.
With several server processes, only one receives updates at a time (a database lease);
set `TELEGRAM_WORKERS=false` on processes that shouldn't run the background tasks.

**Troubleshooting.**

- *"Telegram rejected this token"* — copy it again from BotFather (`/mybots` → API
  Token); revoking it there invalidates the old one.
- *Never shows "Linked ✓"* — press Start in the chat the link opened; if 10 minutes
  passed, get a new link. Check that `TELEGRAM_WORKERS` isn't `false` on every process.
- *Webhook option greyed out* — set `PUBLIC_URL` and restart.
- *Webhook set but nothing arrives* — the address must be reachable from the internet
  over https with a valid certificate; switch back to polling to confirm the rest works.
- *Dead messages in the outbox* — you blocked the bot or the token was revoked; send a
  test after fixing it. Error text shown on the page never contains the token.
- *Changed `SECRET_KEY`* — the saved token can't be decrypted; paste it again.

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
