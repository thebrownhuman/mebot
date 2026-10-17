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
`COOKIE_SECURE`, `TRUST_PROXY`, `PUBLIC_URL`, `GITHUB_TOKEN`, `TELEMETRY`.

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
| Identity | Name, **pronouns**, headline, location, what you're open to, summary, notice period, salary expectation, work authorisation, photo URL, the **assistant greeting**, plus your **contact channels** (see *How recruiters contact you*) |
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
  (offering the contact channels you share, if any) and ends with a hidden
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

  It uses `evals/sample_profile.yaml` and `evals/golden.yaml` (33 questions:
  years, roles, projects, hobbies, unknowns, off-topic, avoid-topics, a prompt
  injection, third-person persona, personal questions that must be declined, meeting and phone-number requests) and makes real API calls with your key, so it costs a few cents.

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

## How recruiters contact you

On **Admin → Profile → Identity** the **Contact channels** list replaces the old Links
and public email/phone fields. Each channel has a type (portfolio, website, email,
LinkedIn, GitHub, Instagram, WhatsApp, Telegram, X, phone, other), a value, a label and
a **Share with recruiters** switch. You can keep up to 30.

- **Only shared channels are ever used.** They appear in the **Contact** panel in the
  recruiter chat header (links open in a new tab), and the bot lists them when someone
  asks to meet, call, interview or hire you ("Can we set up a call?"). It also points to
  the **Leave your contact** form. It never invents times or claims it can book a
  meeting: there is no calendar feature. With nothing shared, it offers only the form.
- **A phone number is never shared by default.** Adding one keeps the switch off.
  Turning it on asks for explicit confirmation (the API needs `confirm_share_phone: true`).
- **WhatsApp takes a username, not a number.** `@yourname` or `wa.me/yourname`; a value
  with 7 or more digits is rejected and you are told to add it as a Phone channel
  instead. Handles for Instagram, X, Telegram and GitHub are turned into profile links;
  website-style types accept only `http(s)` URLs.
- **Switched-off channels are kept for you and never revealed.** They are not sent to
  the AI at all (see Admin → Preview), and an output guard also replaces any
  non-shared value in a reply (and its variants: a phone number with or without `+`
  or spaces, a handle with or without `@`) with `[hidden]`, even if the model quotes
  it in pieces. Any phone-shaped string of 10+ digits is hidden unless it is your shared
  phone. The Logs show `CHANNEL_REDACTED` with a count, never the value. Turning a
  switch off takes effect on the very next message.
- **Don't put your number in Notes or FAQ.** The guard hides it anyway, but Preview
  warns "A phone number appears in your notes", so you can move it to a Phone channel.
- **Limits of the guard:** it can't know a made-up address is wrong. If the AI invents
  an email, it is not one of yours; the prompt forbids it and the golden evals check
  the common cases.
- **Upgrading:** existing links become channels (kind guessed from the domain, shared);
  the old public email becomes a shared Email channel and the old public phone becomes
  a Phone channel that is **not** shared. The old Identity columns stay in the database
  but are no longer used.

Public API: `GET /api/public/contact-channels` returns only the shared channels
(`kind`, `label`, `display`, `href`) and is rate limited.

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

## Import your resume or LinkedIn

Admin → Import fills your profile from files you already have. You review every item
before anything is saved.

**Resume (PDF or .docx, up to 10 MB).** mebot reads the text and asks *your* AI provider
to sort it into jobs, education, skills, projects, interests and links, with strict
instructions to copy only what's written. Then it checks the result against the file:
company, title, school, degree, project and skill names must appear in the resume
(fuzzy, ignoring case and punctuation), and so must every year. Anything that doesn't is
marked **Check this** with the reason and starts as *Skip*. Phone numbers and personal
details (date of birth, marital status, religion and the like; see *What mebot will
never discuss*) are removed. Scanned PDFs have no text to read: use the .docx or the
LinkedIn import. Password-protected PDFs, old `.doc` and macro-enabled files are
refused. You need an AI provider set up first.

**LinkedIn export (ZIP, up to 50 MB).** No AI, so the result is exactly what LinkedIn
has. To get it: LinkedIn → Me → Settings & Privacy → Data privacy → *Get a copy of your
data* → tick Profile, Positions, Education, Skills, Projects (plus Certifications,
Languages, Honors if you want) → request it, wait for the email, upload the ZIP as is.
mebot opens **only** those CSV files (and Email Addresses). Messages, connections,
invitations, phone numbers and everything else in the archive are never read.
Certifications land in Education (shown separately), languages become skills,
honors are proposed as a note, and with several e-mail addresses only the primary one
starts ticked. Year-only dates become January of that year and are flagged.

**Review.** Each item is compared with what's already in your profile: **New** (starts as
*Add*), **Already in profile** (*Skip*), or **Changed** with a field-by-field diff
(*Update*). Jobs match on company + title + start month (±1 month), education on school +
degree, skills by name (aliases like JS/JavaScript count), projects by name. Edit any
item inline, use *Accept all new*, or *Show in source* to see where a resume item came
from. *Apply* saves everything in one go; if one item fails validation (an end date
before the start, say), nothing is saved and that item is highlighted. Re-importing an
updated file only proposes what's new or changed.

**Privacy.** The file is processed in memory and never stored or logged (the server keeps
its name, size and a SHA-256 hash, so uploading the same file twice returns the same
review). The extracted draft is kept for 7 days for you to review, then deleted (or as
soon as you apply or discard it). Limits: 10 imports per hour and one at a time.

## Import projects from GitHub

Admin → Import → **GitHub** turns public repos into project entries, through the same
review screen as resume / LinkedIn imports. Paste up to 10 repo URLs (one per line), or
enter your username and tick repos in the picker (sorted by stars, forks hidden unless
you ask).

**What's read.** Only `api.github.com`: the repo's metadata, language stats, README
(first 30,000 characters), the file list of the root plus one level into `frontend/`,
`backend/`, `client/`, `server/`, `web/`, `api/`, `apps/*`, `packages/*`, and the
contents of dependency manifests only (`package.json`, `requirements*.txt`,
`pyproject.toml`, `Pipfile`, `go.mod`, `Cargo.toml`, `pom.xml`, `build.gradle`,
`composer.json`, `Gemfile`, `pubspec.yaml`, `Dockerfile`, `docker-compose*.yml`,
`prisma/schema.prisma`; at most 15 files of 200 KB each). Config files like
`vercel.json`, `*.tf` or `.github/workflows/*` count by name alone. Source code is never
read, and links in READMEs are never followed. Private repos can't be imported.

**How the entry is built.** Tech is detected from the manifests, not guessed: each tech
has *Evidence* (the file and key that showed it), and languages over 5% of the code are
included. Name, tagline, links, start month (repo created), end month (only for
archived repos) and status (archived / active if pushed in the last 6 months /
completed) come straight from GitHub. If you have an AI provider set up, it writes the
summary and the frontend / backend / infra / data-AI paragraphs from the README only.
The README is treated as data, not instructions. Any number or tech the text mentions
that isn't in the README or the manifests marks the entry **Check this**. Without an AI
provider the summary is the repo description, also flagged. Detected tech you don't
already list is offered as skills, unticked. Re-importing a repo matches the existing
project by its repo URL and shows only what changed.

**Rate limits and the token.** Without a token GitHub allows 60 requests an hour, enough
for about 5 repos. If you hit it, the import says when to try again. For more, create a
[fine-grained token](https://github.com/settings/personal-access-tokens/new) with **no
permissions** (public repositories, read-only is the default) and paste it under *GitHub
token* on the card, or set `GITHUB_TOKEN` on the server. A saved token is encrypted with
your `SECRET_KEY`, shown as its last 4 characters, never logged, and only sent to
`api.github.com`.

## Embed on your site

Put the chat on your portfolio as a floating bubble or an inline panel. Works with plain
HTML, React / Next.js, WordPress, Webflow — anything that can take a `<script>` tag.

**1. Allow your site.** Admin → Widget → *Allowed sites*: add `https://your-site.com`
(and `https://*.your-site.com` for one level of subdomains). https only; plain http just
for `localhost` / `127.0.0.1`. Up to 20 sites. Only these sites can show the chat: the
embed page sends `Content-Security-Policy: frame-ancestors` with exactly this list, and
the launcher settings are readable (CORS) by these sites only, so anyone else who copies
your snippet gets nothing. *Allow any site* exists for testing; it needs a confirm, since
any site could then chat on your API key. Set `PUBLIC_URL` so the snippets use your
public address.

**2. Paste a snippet** (Admin → Widget has them with copy buttons):

```html
<!-- floating bubble, before </body> -->
<script src="https://bot.example.com/widget/v1.js" data-bot="your-slug" async></script>

<!-- inline panel inside your page -->
<div id="mebot-chat"></div>
<script src="https://bot.example.com/widget/v1.js" data-bot="your-slug"
        data-mode="inline" data-target="#mebot-chat" async></script>

<!-- no JavaScript at all -->
<iframe src="https://bot.example.com/embed/your-slug?mode=inline"
        title="Chat" style="width:100%;height:600px;border:0" loading="lazy"></iframe>
```

Optional attributes: `data-position="left|right"`, `data-color="#1d4ed8"` (override the
admin settings), `data-open="true"` (open on load). The launcher lives in a shadow root,
so your CSS can't break it, and the chat iframe is only created when a visitor first
opens it (or on auto-open). On screens under 480px the chat opens full screen; Esc closes
it. Loading the script twice (or on every SPA route) still gives one widget.

**JavaScript API.**

```js
window.MebotQueue = window.MebotQueue || [];       // calls made before the script loads
MebotQueue.push(["on", "open", () => console.log("chat opened")]);
// after load (or keep pushing to MebotQueue):
Mebot.open(); Mebot.close(); Mebot.toggle();
Mebot.on("message", ({ role }) => {});             // "user" | "assistant" | "owner", never the text
```

The host page and the chat talk only through versioned `postMessage` envelopes, checked
on both sides (exact origin and window), and never carry chat content or personal data.

**React / Next.js.**

```tsx
import Script from "next/script";

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        {children}
        <Script src="https://bot.example.com/widget/v1.js" data-bot="your-slug" strategy="lazyOnload" />
      </body>
    </html>
  );
}
```

**WordPress.** Add the floating snippet with a "header & footer code" plugin (footer), or
in a Custom HTML block for the inline panel. **Webflow.** Site settings → Custom code →
*Footer code* for the bubble; an *Embed* element for the inline panel.

**Sites with a strict Content-Security-Policy** need to allow mebot:

    script-src  https://bot.example.com
    frame-src   https://bot.example.com
    connect-src https://bot.example.com

If the chat can't load (site not allowed, CSP blocked, widget off), the launcher removes
itself after at most 8 seconds and logs a `[mebot]` warning in the browser console.

**Notes.** Host sites never call the chat API directly: the iframe runs on mebot's own
origin, so `CORS_ORIGINS` is only for local frontend development. In the iframe, the
browser may keep storage per host site (partitioned), so a visitor's chat on one site
isn't resumed on another. The 3D orb is off by default (adds ~220 KB) and only
downloaded when on. Turning the widget off makes embeds show "unavailable". Each opened
widget chat logs `WIDGET_OPENED` with the host site (only when it is on your list).
`/widget-test` (signed in) is a blank page with the widget, for trying it out.

**Self-hosting.** Run `npm run build` in `frontend/` — the backend serves `/embed/…`
(it sets the per-site headers) and, without nginx, also `/widget/v1.js` and the embed
bundle from `frontend/dist` (`FRONTEND_DIST` to change). The Docker nginx config already
routes `/embed/`, `/widget.js` and `/widget-test` to the backend and serves
`/widget/v1.js` with a one-day cache.

## Dashboard & your data

**Dashboard** (`/admin`). Pick 7, 30 or 90 days. You get chats, visitor messages,
messages per chat, the share of replies the bot couldn't answer, contacts left, your
own Telegram replies, open questions and tokens used, each compared with the period
before. Below that: a daily activity chart (a table version is one click away), the
most-asked questions, where chats came from (the widget's host site, or "Direct page"),
and one status card for the AI provider, Telegram, the widget, pause and today's cap.
Everything is counted per day in your timezone (set it under **Account**). To try the
bot yourself, use the "Try your bot" link. The numbers are cached for 60 seconds.

**Conversations** (`/admin/conversations`). Filter by period, source and what happened
(unanswered, left contact, you replied, a leak was blocked), search message text
(2+ characters), open a transcript with its events and contact card, and delete a
conversation. **Export CSV / JSON** downloads whatever the filters show (at most 50,000
messages; narrow the period beyond that). In CSV, cells that start with `=`, `+`, `-`
or `@` get a leading `'` so a spreadsheet can't run them as formulas. The old
`GET /api/admin/sessions` endpoints still work but are deprecated; use
`/api/admin/conversations`.

**What is stored.** For each chat: the visitor's name (if given), their messages, the
bot's replies, a log of events (unanswered, blocked, widget origin, contact left) and
any contact details they chose to leave. The activity log rows for a chat (session
start, questions) also hold the visitor's IP address; they go when the conversation
goes. Rate limiting keeps only a keyed hash of the IP, in counters removed after a
week. Messages are sent to your AI provider to get answers, and nowhere else.

**Retention.** Under **Account** choose to delete conversations older than 30, 90, 180
or 365 days, or keep them forever. New installs start at 180 days; installs upgraded
from an earlier version keep everything until you choose. The purge runs at start-up
and once a day and is a real delete (messages, contacts, activity log), not a soft
delete. Only counts are logged (`RETENTION_PURGED`). Shortening the window shows how
many conversations it will remove before you save.

**Deleting.** Delete one conversation from its transcript, or everything with
**Delete all conversations now** (type `DELETE` to confirm). Both are permanent.

<a id="telemetry"></a>

## Telemetry & registration

mebot can talk to the **mebot registry** (`https://registry.shivanshmishra.in`, source in
[`registry/`](registry/)) for two things: so the maintainer knows roughly how many installs
are alive, and so you hear about new versions and security advisories. Both are visible and
under your control.

**What is sent, exactly.**

1. *Anonymous heartbeat* (on by default). About once a day (plus a few minutes after start-up):

        {"install_id": "…", "public_key": "…", "version": "0.9.0", "mode": "single"}

   The id is a random key pair generated on first start (`data/install.key`, never leaves your
   server; keep it out of backups you share). The registry stores those four values and the
   first/last time it saw you. No IP address, hostname, URL, e-mail or usage data. At the same
   time mebot fetches the latest version and advisories.
2. *Registration* (opt-in, off by default). Only if you tick **Register this install with the
   mebot project** in setup or under **Account → mebot project**: your contact e-mail
   (your login e-mail unless you enter another), your `PUBLIC_URL` and the mebot version.
   The maintainer is notified. It is re-sent when the e-mail, the site or the major version
   changes. Without `PUBLIC_URL` the status reads "waiting" until you set it.

Chats, your profile, contacts, API keys and everything else stay on your server. Requests
are signed with your install key, so nobody else can change or delete your registration.
The Account page shows the exact JSON of the last heartbeat, and the registry's
[privacy notice](registry/PRIVACY.md) lists everything it stores.

**Turn it off.** Set `TELEMETRY=off` and restart: no heartbeat, registration or update check;
mebot makes no request to the registry at all (so no update banner either). Do this *after*
unticking registration if you were registered, because with telemetry off mebot can't delete
it for you; to remove a registration you can no longer reach, email the maintainer.

**Unregister.** Untick the box under Account → mebot project. mebot deletes the registration
at the registry; if the registry is unreachable it keeps retrying until the deletion is
confirmed (the status shows "removing your registration"). The anonymous heartbeat record
remains until it expires (180 days without a heartbeat).

**Updates.** With telemetry on, the admin panel shows "Update available" (dismiss it per
version) or a red, non-dismissible "Security advisory" while your version is affected.
Dev builds (such as `0.9.0-dev`) never show an update for their own release.

**Safety limits.** mebot only contacts `REGISTRY_URL` (default above; change it only to run
your own registry), follows no redirects, waits at most 5 seconds, reads at most 64 KB and
discards anything that doesn't match the expected shape. A registry outage never affects the
app. If you delete `data/install.key`, mebot creates a new identity on the next start and the
old registration is orphaned (the registry purges it after 180 days); unregister first.

## Tests

    cd backend  && pytest
    cd registry && pytest        # the registry service (its own venv, see registry/README.md)
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
