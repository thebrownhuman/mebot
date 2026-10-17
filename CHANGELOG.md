# Changelog

All notable changes to mebot are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.9.0] - 2026-10-17

First public release.

### Added

- **Self-hostable foundation.** FastAPI + SQLAlchemy backend with Alembic migrations that run
  on start (SQLite by default), React + Vite frontend, everything configured through
  environment variables. Prototype databases are imported automatically.
- **First-run setup and admin auth.** Setup wizard (admin account, AI provider, bot name and
  slug), optional `SETUP_TOKEN`, argon2id passwords, server-side sessions, CSRF protection,
  login rate limits and a CLI password reset.
- **Bring your own AI provider.** Gemini, OpenAI, Anthropic, OpenRouter, Groq, Ollama and any
  OpenAI-compatible server; keys tested before saving and stored encrypted.
- **Structured profile.** Identity, experience, education, skills, projects, interests, FAQ,
  avoid-topics and notes, with a prompt preview.
- **Grounded answers.** Server-computed FACTS (experience, years per skill), third-person
  assistant persona with pronouns, an "I don't know" marker that files open questions,
  golden evals, and a built-in list of personal topics the bot always declines.
- **Chat hardening.** Per-visitor and global message/token caps, pause switch, prompt-leak
  canary, injection logging, optional Cloudflare Turnstile.
- **Telegram.** Notifications, replies that appear in the recruiter's open chat, commands,
  daily digest, polling or webhook, with a retrying outbox.
- **Learning loop.** Answer open questions once (in Admin or Telegram); an AI-cleaned fact
  waits for your approval before the bot knows it.
- **Contact handoff.** Contact channels with per-channel sharing, phone never shared by
  default, output guard that masks unshared values, a "Leave your contact" form.
- **Embeddable widget.** Floating or inline chat for any site via one script tag or an
  iframe, per-site `frame-ancestors`, JavaScript API, light/dark themes.
- **Imports.** Resume (PDF/.docx, AI-assisted and verified against the file), LinkedIn export
  (no AI) and public GitHub repositories (tech detected from manifests), all through one
  review screen.
- **Dashboard and data.** KPIs and charts per period, conversation search, CSV/JSON export,
  retention windows and delete-all.
- **Install registry.** Opt-out anonymous heartbeat, opt-in registration and update /
  security-advisory banners; `TELEMETRY=off` disables every registry request.
- **Packaging.** One multi-arch Docker image (amd64, arm64) serving app, API, embed and
  loader; root `docker-compose.yml`; Railway, Render and Fly configs; CI with lint, tests,
  audit, image build and smoke tests; tagged releases to GHCR.
- **Docs and community files.** Restructured README, `docs/` (configuration reference
  generated from code, providers, deploy guides, security model, upgrading,
  troubleshooting, FAQ), MIT license, contributing guide, security policy, code of conduct.

### Changed

- Visitor and admin IP addresses are stored only as `HMAC-SHA256(SECRET_KEY, ip)`; migration
  0016 hashes existing rows in place. The admin log reports `ip_hash` (prefix) instead of `ip`.
- react-router 7 (fixes GHSA-wrjc-x8rr-h8h6 and GHSA-337j-9hxr-rhxg).
- The embed contact panel follows the widget's light theme.
- The two-container nginx compose moved to `deploy/nginx/` as an advanced example.

### Fixed

- A leaked prompt canary could go undetected when its hex form contained 10+ consecutive
  digits (the phone-number mask ran first). Canaries are now letters only.
- The registry missed `releases.json` edits that landed within one filesystem mtime tick.

[Unreleased]: https://github.com/OWNER/mebot/compare/v0.9.0...HEAD
[0.9.0]: https://github.com/OWNER/mebot/releases/tag/v0.9.0
