# mebot

**Your portfolio's assistant.** A self-hosted chatbot that answers recruiters' questions about
you, from the profile you write, using the AI provider and key *you* choose. It speaks about
you in the third person, says "I don't know" instead of guessing, pings you on Telegram, and
embeds on any website with one script tag.

<!-- Screenshots/GIF go in docs/assets/ (placeholders until the first release is recorded). -->
![Recruiter chat](docs/assets/recruiter-chat.png)
![Admin dashboard](docs/assets/admin-dashboard.png)

MIT licensed · runs in one small container · SQLite · no account, no SaaS.

## Quickstart (10 minutes)

You need Docker. Then:

```bash
mkdir mebot && cd mebot
curl -O https://raw.githubusercontent.com/<owner>/mebot/main/docker-compose.yml
docker compose up -d
```

Open **http://localhost:8080**. Every page redirects to `/setup` on a fresh install:

1. create the admin account (email + a password of 10+ characters),
2. pick an AI provider, paste your key, choose a model and press **Test**,
3. name your bot and pick its slug.

You land in the admin panel (`/admin`). Fill in your profile, open **Try your bot**, and you
have a working assistant. On Linux, if the container stops with "/data is not writable", run
`sudo chown -R 10001:10001 data` once.

**Reachable from the internet on first boot?** Whoever opens `/setup` first becomes the admin.
Put `SETUP_TOKEN=<something random>` in a `.env` file next to `docker-compose.yml` before
starting; the setup form then asks for it.

> `<owner>` is the GitHub account the repository is published under (not decided yet). The
> image is `ghcr.io/<owner>/mebot`; set `MEBOT_OWNER=<owner>` in `.env` for the compose file.

### Deploy to a platform

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/new/template?template=<repo-url>)
[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=<repo-url>)

*Replace `<repo-url>` with the repository URL once it exists; the buttons are placeholders
until then.* Configs: `deploy/railway/railway.json`, `render.yaml`, `fly.toml`. All of them
need a **persistent disk at `/data`** and a single instance; see
[docs/deploy/platforms.md](docs/deploy/platforms.md). Homelab / VPS with a domain, Caddy or
Cloudflare Tunnel, and backups: [docs/deploy/homelab.md](docs/deploy/homelab.md).

## Features

- **Answers only from your profile**: identity, experience, education, skills, projects,
  interests, FAQ, notes. Years of experience and similar numbers are computed by the server,
  not the model. → [profile & grounding](docs/profile.md)
- **Learns from you**: questions it couldn't answer are grouped in an inbox; answer once,
  approve the cleaned fact, and it knows. → [learning loop](docs/learning.md)
- **Stays professional**: always declines personal topics, never reveals contact channels you
  didn't share, guards against prompt leaks.
- **Telegram**: get notified, reply from Telegram straight into the visitor's open chat.
  → [telegram](docs/telegram.md)
- **Embed anywhere**: floating bubble or inline panel, light or dark, locked to the sites you
  allow. → [widget](docs/widget.md)
- **Imports**: resume (PDF/.docx), LinkedIn export, public GitHub repos, all reviewed before
  saving. → [imports](docs/imports.md)
- **Dashboard & data**: activity, top questions, conversation search, CSV/JSON export,
  retention. → [dashboard](docs/dashboard.md)
- **Cost limits**: per-visitor and daily caps, token budget, pause switch.
  → [limits](docs/limits.md)

## Add your API key

mebot never ships or shares a key: you bring your own, entered in setup or
**Admin → AI Provider**, tested before it's saved and stored encrypted.

| Provider | Get a key |
|---|---|
| Google Gemini (free tier) | https://aistudio.google.com/apikey |
| OpenAI | https://platform.openai.com/api-keys |
| Anthropic | https://console.anthropic.com/settings/keys |
| OpenRouter (many models, one key) | https://openrouter.ai/keys |
| Groq | https://console.groq.com/keys |
| Ollama (local, free) | no key: `docker compose --profile ollama up -d` or Ollama on the host |
| Any OpenAI-compatible server | its base URL (vLLM, LM Studio, LiteLLM, …) |

Per-provider notes: [docs/providers.md](docs/providers.md).

## Embed it

```html
<script src="https://bot.example.com/widget/v1.js" data-bot="your-slug" async></script>
```

Add your site under **Admin → Widget → Allowed sites** first. Inline panel, iframe-only,
React/Next.js, WordPress, Webflow and the JavaScript API: [docs/widget.md](docs/widget.md).

## Telegram

Create a bot with [@BotFather](https://t.me/BotFather), paste its token in
**Admin → Notifications**, press **Connect Telegram**. About two minutes; details in
[docs/telegram.md](docs/telegram.md).

## Privacy & telemetry

- Your profile, chats and contacts stay in your data directory. Messages go to your AI
  provider to get answers, and nowhere else.
- API keys and tokens are encrypted with `SECRET_KEY`. **IP addresses are never stored
  raw**: only `HMAC-SHA256(SECRET_KEY, ip)`, in the activity log, admin sessions and rate
  limit counters. The container doesn't write an access log.
- Personal topics (relationships, religion, health, age, …) are always declined and never
  forwarded to you.
- **Telemetry**: an anonymous daily heartbeat (random install id, version, mode) to the mebot
  registry, used to count installs and show update/security banners. Registration with your
  e-mail and site is opt-in. `TELEMETRY=off` stops every registry request.
  → [telemetry](docs/telemetry.md) · [security model](docs/security.md)

## Upgrade

```bash
docker compose stop && tar czf mebot-data-$(date +%F).tar.gz data   # back up first
docker compose pull && docker compose up -d                          # migrations run on start
```

Downgrades aren't supported. Coming from the old two-container compose:
[docs/upgrading.md](docs/upgrading.md).

## Docs

[Configuration](docs/configuration.md) ·
[Providers](docs/providers.md) ·
[Profile & grounding](docs/profile.md) ·
[Learning loop](docs/learning.md) ·
[Limits](docs/limits.md) ·
[Telegram](docs/telegram.md) ·
[Widget](docs/widget.md) ·
[Imports](docs/imports.md) ·
[Dashboard & data](docs/dashboard.md) ·
[Telemetry](docs/telemetry.md) ·
[Security model](docs/security.md) ·
[Upgrading](docs/upgrading.md) ·
[Troubleshooting](docs/troubleshooting.md) ·
[FAQ](docs/faq.md) ·
[Homelab deploy](docs/deploy/homelab.md) ·
[Platform deploys](docs/deploy/platforms.md)

## Development

```
backend/    FastAPI + SQLAlchemy + Alembic (Python 3.11)
frontend/   React + Vite + TypeScript + Tailwind (app, embed, widget loader)
registry/   the install registry service (separate app)
deploy/     container entrypoint, advanced nginx layout, Ollama example
```

```bash
make install && make dev    # backend :8000 + Vite :5173
make test                   # or: bash scripts/dev.sh test
```

See [CONTRIBUTING.md](CONTRIBUTING.md). Security reports: [SECURITY.md](SECURITY.md).
Changes: [CHANGELOG.md](CHANGELOG.md). License: [MIT](LICENSE).
