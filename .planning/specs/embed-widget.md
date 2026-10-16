# Spec: embed-widget

**Created**: 2026-10-17
**Status**: draft
**Author**: Shivansh Mishra
**Epic**: mebot-open-source (Feature 8)

---

## Problem

The bot only lives on its own page. Owners want it on their portfolio (any stack: plain HTML, React, Next.js, WordPress, Webflow) as a chat bubble or an inline section, matching their site's look — and only on their own sites, so nobody else can embed it and burn their API key.

## Goal

One `<script>` tag adds a themed floating chat bubble (or an inline panel) to any site. It loads fast (no 3D orb unless enabled), is isolated from the host page's CSS/JS, works on mobile, and is only frameable from origins the owner allows.

## User Stories

- As the **owner**, I copy `<script src="https://bot.example.com/widget/v1.js" data-bot="shivansh" async></script>` into my portfolio and a bubble appears bottom-right in my brand colour.
- As the **owner**, I add `https://shivansh.dev` to allowed sites; a stranger pasting my snippet on their site gets nothing.
- As a **recruiter** on mobile, I tap the bubble and get a full-screen chat; I close it and keep browsing.
- As the **owner**, I preview my widget live in admin while changing colours and suggested questions.

## Requirements

### Must-have
1. **Schema (Alembic 0011)** `widget_settings` (one per bot): `id`, `bot_id` unique, `enabled BOOLEAN DEFAULT true`, `allowed_origins TEXT` (JSON array), `allow_any_origin BOOLEAN DEFAULT false`, `primary_color TEXT DEFAULT '#0f766e'`, `theme TEXT DEFAULT 'auto'` (`light|dark|auto`), `position TEXT DEFAULT 'right'` (`right|left`), `title TEXT NULL` (default "{first_name}'s assistant"), `avatar_url TEXT NULL`, `launcher_label TEXT NULL` (e.g. "Ask about me"), `suggested_questions TEXT` (JSON array, ≤ 6, each ≤ 80 chars), `show_orb BOOLEAN DEFAULT false`, `auto_open_seconds INT NULL` (NULL = never; 5–120), `created_at`, `updated_at`.
2. **Origin rules:** each origin `scheme://host[:port]`, https required except `http://localhost[:port]` / `http://127.0.0.1[:port]`; optional single-level subdomain wildcard `https://*.example.com`; no paths/queries; max 20. Normalised (lowercase host, default ports stripped).
3. **Embed page** `GET /embed/{slug}` — the recruiter chat in compact embed mode (separate Vite entry `embed.html`, own bundle):
   - Response header `Content-Security-Policy: frame-ancestors 'self' <allowed origins>` (or `*` only when `allow_any_origin`); `enabled=false` or unknown slug → small "unavailable" page with `frame-ancestors 'none'`.
   - No `X-Frame-Options` on this route (CSP governs); all other routes keep `X-Frame-Options: DENY` + `frame-ancestors 'self'` (add if missing).
   - Bundle budget: ≤ 150 KB gzipped JS without orb; three.js orb lazy-loaded only when `show_orb`.
   - Reads settings from `GET /api/public/widget/{slug}` → theme, colours, title, avatar, greeting (7b), suggested questions, launcher label, `max_message_chars`, Turnstile key, owner first name.
   - Suggested-question chips shown before the first message; clicking sends it.
   - Includes Contact panel (7c), contact form (7), owner replies (7), limits/paused messages (6).
   - Session id stored in the iframe's localStorage (try/catch; partitioned storage acceptable — per host site).
4. **Loader script** `GET /widget/v1.js` (vanilla TS → ES2017 IIFE, ≤ 8 KB gzipped, no deps), long-cache with versioned path; `/widget.js` 302 → `/widget/v1.js`.
   - Reads `data-bot` (required), optional overrides `data-position`, `data-color`, `data-open="true"`, `data-mode="inline"` + `data-target="#css-selector"`.
   - Floating mode: shadow-DOM-hosted launcher button (so host CSS can't break it) + an iframe panel (`/embed/{slug}?mode=floating`) lazily created on first open (no iframe load before interaction unless `auto_open_seconds`/`data-open`).
   - Inline mode: iframe inserted into target element, full width, height from postMessage resize (min 420px).
   - Panel: 380×600 desktop, full-screen below 480px viewport width; Esc closes; focus moves into panel on open and back to launcher on close; launcher `aria-label`, `aria-expanded`.
   - JS API: `window.Mebot.open()`, `.close()`, `.toggle()`, `.on('open'|'close'|'message', fn)`; queued calls before load supported via `window.MebotQueue`.
   - Unread badge on launcher when an owner reply (#7) arrives while closed.
   - Multiple script tags / double load → single instance.
5. **postMessage protocol** (versioned `{ source: "mebot", v: 1, type, payload }`):
   - iframe → parent: `ready`, `resize {height}`, `close`, `unread {count}`, `message {role}` (no content), `open-link {href}` (only http(s)/mailto; parent opens in new tab).
   - parent → iframe: `open`, `close`, `host-info {origin}`.
   - Loader accepts messages only where `event.origin === backend origin` and `event.source === iframe.contentWindow`; iframe accepts parent messages only with matching schema, ignores everything else. Never send chat content or PII via postMessage.
6. **Leak-block bubble replacement (carry-over from #6):** chat stream may end with a control frame `\x1e{"type":"replace","content":"<safe text>"}`. Backend strips any `\x1e` from model output. Recruiter UI (standalone + embed) replaces the current bubble with `content` on receipt. Applies to leak-block and channel-redaction cut-offs.
7. **CORS:** public API stays same-origin for the embed (iframe is on the backend origin). `CORS_ORIGINS` remains for dev only; document that host sites never call the API directly.
8. **Admin API:** `GET/PUT /api/admin/widget` (validation per req 1–2; `allow_any_origin=true` requires `confirm_any_origin: true`), `GET /api/admin/widget/snippets` → `{ script, inline, iframe }` strings using `PUBLIC_URL` (or request base URL).
9. **Admin UI "Widget" page:** settings form (colour picker + hex, theme, position, title, avatar URL, launcher label, suggested questions editor with drag/arrow reorder, orb toggle with size note, auto-open), allowed sites list with add/validate/remove, "Allow any site" toggle with warning + confirm, live preview (renders the loader in an in-page sandbox pointing at own embed), copy buttons for the three snippets, status line ("Widget allowed on 2 sites"). Dashboard hint if widget enabled but no allowed origins.
10. **Test page** `GET /widget-test` (admin-only) — a blank host page that loads the loader for manual testing.
11. **Analytics hook:** `WIDGET_OPENED` access_log event per session (origin stored = host origin from `host-info`, validated against allowed list; not personal data). Feeds #11.
12. **Docs:** README "Embed on your site" — script, inline, iframe, React/Next.js example (`<Script strategy="lazyOnload">`), WordPress/Webflow notes, allowed sites, CSP note for host sites with strict CSP (`frame-src`/`script-src` additions).

### Nice-to-have
- `data-lang` to force UI language.
- Launcher hidden on specified paths.

### Out of scope
- npm package / React component library (#16).
- Per-origin different settings.
- Server-side analytics dashboard (#11).

## Data Model

Alembic 0011 `widget_settings` (req 1). snake_case, UUID id, UTC timestamps; one row per bot, overwrite in place.

## API Changes

```
GET  /api/public/widget/shivansh → { "title": "Shivansh's assistant", "primary_color": "#0f766e", "theme": "auto", "position": "right",
       "avatar_url": null, "launcher_label": "Ask about me", "greeting": "Hi! I'm Shivansh's assistant…",
       "suggested_questions": ["What does he work on?", "Tech stack?"], "show_orb": false, "max_message_chars": 1000,
       "turnstile_site_key": null, "owner_first_name": "Shivansh" }
PUT  /api/admin/widget { "allowed_origins": ["https://shivansh.dev", "https://*.shivansh.dev"], "primary_color": "#1d4ed8", ... } → 200 | 422
GET  /api/admin/widget/snippets → { "script": "<script src=\"https://bot.example.com/widget/v1.js\" data-bot=\"shivansh\" async></script>", "inline": "...", "iframe": "..." }
GET  /embed/shivansh   (HTML; CSP frame-ancestors)
GET  /widget/v1.js     (JS; Cache-Control: public, max-age=86400)
```

## UI Changes

New: loader, embed bundle, admin Widget page, test page. Recruiter standalone page gets suggested chips + replace-frame handling.

## Edge Cases

1. Snippet on a non-allowed site → browser refuses to frame (CSP); loader shows nothing (listens for `ready` timeout 8s, then removes launcher and logs a console warning naming the origin).
2. No allowed origins and `allow_any_origin=false` → widget works only on the backend's own origin; admin hint shown.
3. Host page CSS (`* { all: unset }`, huge z-index) → launcher in shadow DOM with `z-index: 2147483000`; panel iframe unaffected.
4. Host page strict CSP blocks our script/frame → documented directives; loader fails silently with console hint.
5. Script included twice / SPA route changes → one instance; `Mebot` API idempotent.
6. Third-party storage partitioned / blocked → session per host site; if storage throws, session lives in memory only.
7. Mobile keyboard covering input → full-screen panel uses `100dvh`; input stays visible.
8. Message from another window posing as mebot → rejected (origin + source check).
9. `auto_open_seconds` set → opens once per browser session (sessionStorage flag in iframe), not on every page.
10. Wildcard origin `https://*.example.com` → matches `https://a.example.com`, not `https://example.com` or `https://a.b.example.com`.
11. Owner disables widget → embed returns unavailable page; existing open panels show "unavailable" on next request.
12. Leak/redaction cut mid-stream → replace frame swaps bubble text in both standalone and embed.

## Testing Criteria

- Backend: origin validation/normalisation/wildcards; CSP header per settings (allowed list, any, disabled, unknown slug); other routes have DENY/frame-ancestors 'self'; public widget endpoint; admin GET/PUT validation + confirm_any_origin + auth/CSRF; snippets use PUBLIC_URL; `\x1e` stripped from model output and replace frame emitted on leak/redaction; `WIDGET_OPENED` origin validated.
- Loader (Vitest + jsdom): data-attr parsing; single instance; lazy iframe creation; open/close/toggle API + queue; Esc + focus management; postMessage origin/source checks (spoof rejected); unread badge; inline mode resize; ready-timeout removal.
- Embed app: settings applied (colour CSS vars, theme, title), suggested chips send message, replace frame handling, orb not loaded when disabled (dynamic import not called).
- Bundle size check script in CI step: loader ≤ 8 KB gz, embed JS ≤ 150 KB gz (fails test if exceeded).
- Admin Widget page: form validation, origins editor, any-origin confirm, copy snippets, live preview renders.
- `pytest`, `npm run typecheck && npm run build && npm test` green.

## Dependencies

- Features 1–7c (`feature/contact-handoff`).
- No new runtime deps (loader is vanilla). A size check may use `gzip-size` (dev).

---

## Gate 1

- [x] Problem specific · [x] Goal measurable · [x] User stories · [x] Must/nice/out split
- [x] Table has id + timestamps · [x] Types defined · [x] Overwrite strategy stated
- [x] Endpoints + examples · [x] snake_case JSON · [x] standard error shape
- [x] 12 edge cases · [x] Happy + edge tests · [x] Dependencies listed
