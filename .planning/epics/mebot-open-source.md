# Epic: mebot-open-source

**Created**: 2026-10-12
**Status**: planning
**Owner**: Shivansh Mishra

---

## Why

Turn the personal me-bot prototype into an open-source product anyone can run: a portfolio chatbot that answers recruiter questions accurately from the owner's data, notifies the owner on Telegram, and embeds into any site. Users bring their own LLM API key and either self-host (`docker compose up`) or, later, use the maintainer's hosted platform. The maintainer gets an opt-in notification whenever a new install registers.

---

## Success Criteria

- [ ] A stranger clones the repo, runs `docker compose up`, completes a first-run setup screen (admin account + LLM provider key), and has a working bot in under 10 minutes â€” no code edits.
- [ ] Admin portal is login-protected; every public endpoint is rate-limited; no admin data reachable without auth.
- [ ] Bot answers "how many years of experience / with X" correctly from computed facts, and says "I don't know" (and pings Telegram) when data is missing.
- [ ] Owner gets Telegram messages for new chats and unanswered questions, and can reply from Telegram back into the chat/FAQ.
- [ ] Bot embeds on an external portfolio via one `<script>` tag, restricted to allowed origins.
- [ ] Opt-in install registration notifies the maintainer on Telegram; `TELEMETRY=off` fully disables it.
- [ ] Works with at least OpenRouter, Gemini, OpenAI, Anthropic, Groq, Ollama.
- [ ] CI runs backend + frontend tests and builds the Docker image on every PR.

---

## Features

| # | Feature | Status | Spec | Plan | Depends On | Effort |
|---|---------|--------|------|------|------------|--------|
| 1 | Foundation: repo restructure, config, multi-tenant schema, migrations | review | [spec](../specs/foundation.md) | â€” | â€” | M |
| 2 | First-run setup + admin auth | review | [spec](../specs/setup-auth.md) | â€” | #1 | M |
| 3 | LLM provider layer (owner adds own key at setup, encrypted) | review | [spec](../specs/llm-provider.md) | â€” | #1, #2 | M |
| 4 | Structured profile data + admin data pages | review | [spec](../specs/profile-pages.md) | â€” | #2 | L |
| 5 | Prompt builder: computed facts + grounded answers | review | [spec](../specs/grounded-answers.md) | â€” | #3, #4 | M |
| 6 | Public chat hardening: rate limits, daily cap, injection guard | review | [spec](../specs/chat-hardening.md) | â€” | #3 | S |
| 7 | Telegram notifications + reply-back loop | review | [spec](../specs/telegram.md) | â€” | #5 | M |
| 7b | Learning loop: open-questions inbox, owner answers â†’ AI-cleaned facts (approve first), professional-topic filter, assistant persona (3rd person) | review | [spec](../specs/learning-loop.md) | â€” | #7 | M |
| 7c | Contact handoff: on meeting/contact requests bot shares owner-chosen channels (portfolio, email, Instagram, WhatsApp username, LinkedInâ€¦); per-channel "share" toggle; phone number never shared by default; no calendar booking | review | [spec](../specs/contact-handoff.md) | â€” | #7b | S |
| 8 | Embeddable widget + allowed origins + theming | review | [spec](../specs/embed-widget.md) | â€” | #6 | M |
| 9 | Imports: resume PDF/DOCX + LinkedIn export ZIP | review | [spec](../specs/imports.md) | â€” | #3, #4 | M |
| 10 | Import: GitHub repo â†’ project entry | review | [spec](../specs/github-import.md) | â€” | #9 | S |
| 11 | Dashboard + conversations + analytics | review | [spec](../specs/dashboard-analytics.md) | â€” | #4, #7 | M |
| 12 | Install registry + opt-in telemetry | review | [spec](../specs/install-registry.md) | â€” | #2 | M |
| 13 | Open-source packaging: single image, docs, CI, deploy buttons | review | [spec](../specs/packaging-release.md) | â€” | #1â€“#12 | M |
| 14 | Retrieval (embeddings) for large profiles | review | [spec](../specs/retrieval.md) | â€” | #5 | M |
| 15 | Hosted mode (MODE=hosted, signups, per-user bots) | todo | â€” | â€” | #1â€“#13 | L |
| 16 | **LAST** â€” Paid plans: plugin library (JS/CSS SDK) + monthly subscription | todo | â€” | â€” | #15 | L+ (split at spec) |

Effort: S â‰ˆ â‰¤1 day, M â‰ˆ 1â€“3 days, L â‰ˆ 3 days (split at spec time if larger).

---

## Feature Briefs

### Feature 1: Foundation
Restructure into `backend/`, `frontend/`, `deploy/`. Add settings via env (`MODE`, `SECRET_KEY`, `DATABASE_URL`, `TELEMETRY`) with `.env.example`. New schema with `bot_id` on every table, Alembic (or simple versioned SQL) migrations, SQLite default. Remove hardcoded "talkaboutshivansh" routes and personal Modelfile. Add pytest + Vitest scaffolding.

### Feature 2: First-run setup + admin auth
If no admin exists, every route redirects to `/setup`: create admin (email + password, argon2 hash), bot name/slug, registration consent checkbox. Session cookie (httpOnly, SameSite) auth, login/logout, CSRF protection. All `/api/admin/*` routes require auth; CORS no longer `*`.

### Feature 3: LLM provider layer
One `LLMClient` interface over OpenAI-compatible APIs (LiteLLM or thin httpx adapters): OpenRouter, Gemini, OpenAI, Anthropic, Groq, Ollama. Admin "AI Provider" page: provider, model, key, temperature, max tokens, optional fallback model, "Test connection". Keys encrypted at rest (Fernet from `SECRET_KEY`), never returned to the browser in full.

### Feature 4: Structured profile data + admin pages
Replace the text blob with tables: identity, experience (company, title, start/end), education, skills (level, years), projects (summary, frontend, backend, infra, role, links), hobbies/interests, FAQ, avoid-topics. Admin portal sidebar with one CRUD page per section. Migrate existing blob into "notes" field.

### Feature 5: Prompt builder
Server computes facts (total experience, per-skill years, current role, project count) from dates and injects them as explicit statements. Prompt is assembled from structured sections; bot answers only from them, otherwise returns a structured "unknown" marker that the backend detects. Golden-question test suite.

### Feature 6: Public chat hardening
Per-IP and per-session rate limits (configurable, e.g. 10/min, 50/day), global daily message cap, message length limit, prompt-injection/system-prompt-leak guard, optional Turnstile. Admin "Limits" page.

### Feature 7: Telegram
Admin "Notifications" page: bot token + chat ID + test button, event toggles (new session, every question, unanswered, contact left). Telegram webhook or long-poll: owner replies to an unanswered-question message â†’ answer delivered into the live chat and optionally saved to FAQ. In-chat "leave your contact" flow.

### Feature 8: Embeddable widget
`/widget.js` drops a floating bubble + iframe chat on any site via `<script src=â€¦ data-bot="slug">`. Admin "Widget" page: copy snippet, allowed origins list (enforced server-side via CORS + frame-ancestors), colours, avatar, greeting, suggested questions. Standalone public page at `/{slug}` remains.

### Feature 9: Imports â€” resume + LinkedIn
Upload PDF/DOCX resume â†’ text extraction â†’ LLM structured extraction into Feature 4 schema â†’ diff/review screen â†’ save. Upload LinkedIn "Get a copy of your data" ZIP â†’ parse Positions/Education/Skills/Projects CSVs deterministically. No scraping.

### Feature 10: Import â€” GitHub
Paste repo URL â†’ GitHub public API pulls README, languages, file tree â†’ LLM drafts a project entry (frontend/backend/infra) â†’ review â†’ save. Optional: import all pinned repos for a username.

### Feature 11: Dashboard + conversations
Dashboard: chats today/week, top questions, unanswered rate, provider token usage. Conversations page: list, read, delete, export. Replaces current AdminPage/drawers.

### Feature 12: Install registry + telemetry
Separate tiny service (`registry/`) on maintainer's server: `POST /register` (email, site URL, version â€” only with consent) â†’ Telegram ping to maintainer; `POST /heartbeat` (random install ID + version, anonymous, daily). App side: consent from setup, toggle in Account page, `TELEMETRY=off` env kill switch, documented in README. Registry returns latest version â†’ update banner in admin.

### Feature 13: Packaging
Single Docker image (FastAPI serves built frontend) + compose file; no Ollama required. Published to GHCR. README with GIF + quickstart, docs for each provider, Telegram setup, widget embed. MIT license, CONTRIBUTING, GitHub Actions CI (lint, tests, typecheck, image build). Deploy buttons: Railway, Render, Fly.

### Feature 14: Retrieval
Chunk + embed profile/project content (sqlite-vec), retrieve top-k per question, keep computed facts always in prompt. Only needed when profile exceeds context budget; gate behind size threshold.

### Feature 15: Hosted mode
`MODE=hosted`: public signup, many users each with own bot + own encrypted key, subdomain/slug routing, per-tenant limits, admin-of-admins view, maintainer Telegram ping on signup. Billing is Feature 16.

### Feature 16: Paid plans â€” plugin library + monthly subscription (do LAST)
Turn the hosted platform into a paid service. Customers don't host anything: they install a drop-in plugin (npm package + CDN `<script>`/CSS, React component, framework-agnostic web component) into their own site/UI, sign up on the hosted platform, add their own LLM API key, and connect the plugin to their bot with a public bot key. Connecting/serving requires an active monthly subscription.
- Billing: Razorpay subscriptions (UPI AutoPay, cards; India) and/or Stripe (international). Webhook-driven subscription state; plugin/API returns "subscription inactive" when unpaid; grace period on failed renewal.
- Plans: e.g. Free trial (N days / N messages) â†’ Monthly. Plan limits enforced alongside #6 rate limits.
- Customer dashboard: plan, invoices, cancel, usage. Maintainer Telegram ping on new subscription / cancellation.
- Plugin: versioned SDK, theming via CSS variables, public bot key (not the LLM key), origin allow-list per bot.
- Legal before launch: terms of service, privacy policy, refund policy, GST invoicing (India), DPDP/GDPR data handling.
- Self-host stays free and open source; paid tier is convenience + hosting.

---

## Risks

- **Telemetry trust.** Hidden or default-on personal data collection would damage the project's reputation and breach GDPR/DPDP. Mitigation: explicit consent, anonymous heartbeat only, documented kill switch.
- **Hallucinated answers** about the owner (wrong years, invented skills) are worse than no answer. Mitigation: computed facts, unknown-marker detection, golden-question tests (Feature 5).
- **Cost abuse** of the owner's API key through the public chat. Mitigation: Feature 6 must ship before the widget (Feature 8) is promoted.
- **Provider API differences** (Anthropic/Gemini streaming formats). Mitigation: LiteLLM or per-provider adapters with contract tests.
- **LinkedIn changes the export format.** Mitigation: tolerant CSV parsing + resume PDF fallback.
- **Telegram reply-back needs a public webhook**; self-hosters behind NAT can't receive one. Mitigation: long-polling mode as default.
- **Multi-tenant leakage** in hosted mode. Mitigation: `bot_id` scoping enforced in repository layer from Feature 1, tested.

---

## Notes

- Decisions: Python/FastAPI backend, React/Vite/TS frontend, SQLite default, fresh git history (baseline commit `cd3d340`).
- Self-host (MODE=single) is the priority; Features 1â€“13 ship that. 14â€“15 come after.
- Existing 3D orb UI is kept as the public chat look.
- Minimum viable release: Features 1â€“8 + 13.
- Feature 16 (paid plans) is deliberately the very last item â€” only after hosted mode (#15) is stable.
