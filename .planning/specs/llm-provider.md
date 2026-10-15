# Spec: llm-provider

**Created**: 2026-10-15
**Status**: draft
**Author**: Shivansh Mishra
**Epic**: mebot-open-source (Feature 3)

---

## Problem

The bot only talks to a local Ollama with a hardcoded model. Anyone installing mebot must use their own LLM account, but there is no way to enter an API key, pick a provider/model, or verify it works. The project never ships or shares a key — the installer adds their own.

## Goal

Setup cannot complete until the owner adds their own provider + model (+ key where required) and a live test call succeeds. Chat then uses that configuration. The key is stored encrypted and never sent back to the browser.

## User Stories

- As a **self-hoster**, during setup I pick a provider (e.g. Gemini), paste my own API key, choose a model, press Test, and only after it passes can I finish setup.
- As the **owner**, I can later change provider/model/key in Admin → AI Provider, test it, and save.
- As a **recruiter**, if the owner's key stops working I see a polite "the assistant is unavailable right now" message, not a raw error.

## Requirements

### Must-have
1. **Providers:** `openrouter`, `gemini`, `openai`, `anthropic`, `groq`, `ollama`, `openai_compatible` (custom base URL). Implement with thin httpx adapters behind one interface (no LiteLLM — keeps the image small and streaming explicit):
   ```python
   class LLMClient(Protocol):
       async def stream_chat(self, messages, *, model, temperature, max_tokens) -> AsyncIterator[str]: ...
       async def test(self, *, model) -> TestResult: ...   # tiny 1-token call
       async def list_models(self) -> list[str]: ...       # best-effort, may return []
   ```
   OpenRouter / OpenAI / Groq / openai_compatible share one OpenAI-compatible adapter (`/chat/completions`, SSE). Gemini uses its OpenAI-compatible endpoint (`https://generativelanguage.googleapis.com/v1beta/openai/`). Anthropic gets its own adapter (`/v1/messages`, SSE, `x-api-key`, `anthropic-version`). Ollama keeps the existing adapter (`think:false`).
2. **Key required:** every provider except `ollama` requires a non-empty key. `openai_compatible` requires `base_url`; key optional.
3. **Storage (Alembic 0004):** `llm_configs`: `id`, `bot_id` (unique), `provider TEXT`, `model TEXT`, `base_url TEXT NULL`, `api_key_encrypted TEXT NULL`, `api_key_last4 TEXT NULL`, `temperature REAL DEFAULT 0.4`, `max_tokens INTEGER DEFAULT 600`, `last_tested_at NULL`, `last_test_ok BOOLEAN NULL`, `created_at`, `updated_at`. Key encrypted with Fernet derived from `SECRET_KEY` (HKDF, info=`mebot-llm-key`).
4. **Setup becomes a 3-step wizard** (extends Feature 2):
   1. Account (email, password)
   2. AI provider — provider select, key (password field), model (dropdown from `list_models` when available + free text), base URL for custom, **Test** button
   3. Bot name/slug + registration consent
   - `POST /api/setup` now also requires `llm: { provider, model, api_key?, base_url? }`. Backend **runs the test call itself** inside setup; if it fails → 422 `LLM_TEST_FAILED` with provider's message (sanitised, key never echoed) and nothing is created.
   - `POST /api/setup/llm-test` (public, only while setup required, CSRF + rate-limited 10/min/IP) lets step 2 test before final submit.
   - Existing installs upgrading with an admin but no `llm_configs` row: admin login works, chat returns 503 `LLM_NOT_CONFIGURED`, admin UI shows a blocking banner linking to AI Provider page.
5. **Admin API:**
   - `GET /api/admin/llm` → `{ provider, model, base_url, has_key, api_key_last4, temperature, max_tokens, last_tested_at, last_test_ok }` — never the key.
   - `PUT /api/admin/llm` → same fields + optional `api_key` (omitted = keep existing). Runs test before saving; failure → 422, old config kept.
   - `POST /api/admin/llm/test` → test with submitted or saved config.
   - `GET /api/admin/llm/models?provider=…` → model list using submitted/saved key (best-effort).
   - `GET /api/admin/llm/providers` → static list with display name, key required, default base URL, key-signup URL, suggested models.
6. **Chat:** `/api/chat` builds the client from the bot's `llm_configs`. Provider errors (401, 429, 5xx, timeout) are logged to `access_log` (`LLM_ERROR`, status code, provider — no key, no full body) and the recruiter gets a fixed friendly message. Remove hardcoded `OLLAMA_MODEL`/fallback model from chat path; `OLLAMA_HOST` env becomes only the default base URL suggestion for the ollama provider.
7. **Admin UI page "AI Provider":** shows current provider/model, `••••1234`, last test status; edit form with Test + Save; link "Get a key" per provider.
8. **Security:** key never logged, never in responses, never in error messages (scrub before returning provider errors). Key field `autocomplete="off"`. Changing `SECRET_KEY` makes stored key undecryptable → treated as "not configured" with clear admin message, no crash.
9. **Docs:** README "Add your API key" section with where to get a key for each provider; no project key exists.

### Nice-to-have
- Fallback provider/model if primary fails.
- Token usage capture per message (for dashboard #11).

### Out of scope
- Hosted platform key management (#15), spend caps (#6), embeddings (#14).

## Data Model

See Requirement 3. snake_case, UUID ids, UTC timestamps. One active config per bot (unique `bot_id`); no soft delete needed (overwrite in place, `updated_at`).

## API Changes

```
POST /api/setup
{ "email": "...", "password": "...", "bot_name": "...", "bot_slug": "...", "registration_consent": false,
  "llm": { "provider": "gemini", "model": "gemini-2.5-flash", "api_key": "AIza..." } }
→ 201 | 422 { "error": { "code": "LLM_TEST_FAILED", "message": "Gemini rejected the API key (401).", "status": 422 } }

POST /api/setup/llm-test   { "provider", "model", "api_key"?, "base_url"? } → { "ok": true, "latency_ms": 640 } | 422
GET  /api/admin/llm        → { "provider": "gemini", "model": "gemini-2.5-flash", "has_key": true, "api_key_last4": "x9Qa", ... }
PUT  /api/admin/llm        { "provider", "model", "api_key"?, "base_url"?, "temperature"?, "max_tokens"? } → 200 | 422
POST /api/admin/llm/test   → { "ok": true, "latency_ms": 512 } | 422
GET  /api/admin/llm/models?provider=openrouter → { "models": ["..."] }
GET  /api/admin/llm/providers → { "providers": [ { "id": "gemini", "name": "Google Gemini", "key_required": true, "key_url": "https://aistudio.google.com/apikey", ... } ] }
```

## UI Changes

- Setup: single form → 3-step wizard with progress indicator; step 2 "Next" disabled until Test passes; going back keeps entered values.
- Admin: new "AI Provider" page; blocking banner when not configured or last test failed.
- Recruiter chat: friendly unavailable message on LLM error.

## Edge Cases

1. Invalid key → test fails, setup blocked, error shows provider's reason without the key.
2. Valid key, wrong/unavailable model → test fails with model message.
3. Provider rate-limits the test (429) → shown as "rate limited, try again", setup not completed.
4. Network timeout (10s) on test → clear timeout error.
5. Key revoked after setup → chat returns friendly message; admin banner shows last test failed after next failure.
6. `SECRET_KEY` changed → key can't decrypt → treated as not configured, admin prompted to re-enter.
7. Ollama selected but not reachable → test fails "cannot reach Ollama at …".
8. PUT without `api_key` keeps existing key; switching provider without new key → 422 (key belongs to old provider).
9. Provider returns error body containing the key (some echo headers) → scrubbed before response/log.
10. Upgrade from Feature 2 install with no LLM config → login works, chat 503, banner shown.

## Testing Criteria

- Adapters: request shape + SSE parsing for openai-compatible, anthropic, gemini (via compat), ollama — using `respx`/mock transport, no real network.
- Setup: blocked without llm; blocked on failed test; success stores encrypted key (DB value ≠ plaintext); llm-test endpoint only while setup required; rate-limited.
- Admin: GET never returns key; PUT keeps key when omitted; PUT with failed test keeps old config; provider switch without key → 422.
- Chat: uses configured provider; provider 401/429/timeout → friendly message + `LLM_ERROR` log without key.
- Crypto: wrong SECRET_KEY → not-configured path.
- Frontend: wizard step gating (Next disabled until test ok), back keeps values, admin page masks key, banner on not-configured.
- `pytest`, `npm run typecheck && npm run build && npm test` green.

## Dependencies

- Features 1, 2 (`feature/setup-auth`).
- Python: `cryptography`, `respx` (dev). No LiteLLM.

---

## Gate 1

- [x] Problem specific · [x] Goal measurable · [x] User stories · [x] Must/nice/out split
- [x] Tables have id + timestamps · [x] Types defined · [x] Overwrite strategy stated
- [x] Endpoints + examples · [x] snake_case JSON · [x] standard error shape
- [x] 10 edge cases · [x] Happy + edge tests · [x] Dependencies listed
