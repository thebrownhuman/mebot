# Feature 14: Retrieval for large profiles

Epic: `.planning/epics/mebot-open-source.md` · Depends on: #5 (grounding/FACTS), #7b (learned facts), #9/#10 (imports make profiles big) · Size: M · Worker: Sonnet

## Problem

Today `render_profile()` puts the whole profile in every system prompt. After resume + LinkedIn + GitHub imports, profiles can reach tens of thousands of tokens. That costs the owner money on every message, can exceed small context windows (Groq/Ollama models), and dilutes grounding. Small profiles work fine as they are and must not change.

## Goal

When the rendered profile exceeds a token budget, send only the relevant parts per question. Always-on parts stay in the prompt. Answers stay grounded, and `[[UNANSWERED]]` must not fire just because retrieval missed something.

## Design

### Gate (no behaviour change for small profiles)
- New setting `RETRIEVAL_THRESHOLD_TOKENS` (default 6000), plus a per-bot admin override: `auto` / `always` / `off`.
- `auto`: if `approx_tokens(render_profile(p)) <= threshold`, use the full profile exactly as today (byte-identical prompt; add a test). Otherwise use retrieval.

### Always in prompt (never retrieved)
Identity, contact/share rules, computed FACTS (`render_facts`), avoid list, assistant persona/rules. Add a compact **outline**: section names plus item titles (job titles+companies, project names, degree names) so the model knows what exists even when details weren't retrieved.

### Chunking
- One chunk per natural item: each experience entry, project, education entry, skill group, FAQ pair, approved learned fact, and notes split at roughly 300 tokens. Each chunk carries its section heading and item title, so it reads on its own.
- Chunks are stored in a new table `knowledge_chunks` (bot_id, section, item_key, text, content_hash, embedding BLOB nullable, embedding_model, updated_at). Migration `0017`.
- Reindex is incremental, by content_hash. It runs after profile save, import apply, and learned-fact approve (a background task, never in the request path). Chat checks a profile-version stamp and reindexes lazily if stale.

### Ranking: lexical required, embeddings optional
- **Baseline (always available, no network):** SQLite FTS5 BM25 over the chunks. FTS5 ships with Python's sqlite3, so there's no new dependency. Add a test that fails clearly if FTS5 is missing.
- **Optional embeddings:** use them when the owner's provider supports an embeddings endpoint (OpenAI, OpenRouter, Gemini, Ollama, custom OpenAI-compatible) and the owner enables it in admin (default off, since it costs money on their key). Add `embed(texts, model)` to the adapter protocol. Anthropic and Groq report "unsupported" and the toggle is disabled with an explanation. Vectors are float32 BLOBs; cosine is computed in Python (profiles are hundreds of chunks, so no sqlite-vec or numpy needed). **Decision vs epic:** sqlite-vec dropped (native extension, packaging risk on Windows/Docker, no gain at this scale).
- With embeddings on: hybrid score = reciprocal-rank fusion of BM25 and cosine.
- Embedding calls go through existing rate limits and usage accounting, are batched, and are cached by content_hash + model. If an embedding fails, fall back to lexical silently and log it. Never block chat.

### Query and selection
- Query = the current user message + the previous user message (for follow-ups like "what stack did it use?").
- Fill top-ranked chunks until a retrieval budget is reached (default 2500 tokens, setting `RETRIEVAL_BUDGET_TOKENS`). Keep at least the top 3 if any match.
- **Low-confidence fallback:** if nothing scores above a floor, include the most recent experience plus the top projects, not nothing. Then the model either answers or flags UNANSWERED correctly.
- The order in the prompt follows the profile section order, not the score (more readable and stable).

### Prompt and guards
- `build_system_prompt` takes the knowledge text from a new `knowledge_for(bot, messages)` function. Callers don't care which mode was used.
- Marker, leak, personal and channel guards are unchanged. The prompt rule changes from "If it's not in the profile" to "If it's not in the profile excerpt or outline", so the outline counts as evidence that something exists.

### Admin UI (Settings → Knowledge)
- Show mode (full / retrieval) and why (token count vs threshold), chunk count, last indexed, and embedding status.
- Controls: mode select (auto/always/off), embeddings toggle + model field (only when supported), and a "Rebuild index" button.
- Conversation detail (#11): show which chunk titles were used for each bot reply (store chunk ids on the message, nullable). This helps the owner debug wrong answers.
- Works at 375/768/1440 with loading/empty/error states.

### Analytics
Add a `retrieval_mode` counter per day plus average prompt tokens, so the owner sees the savings on the dashboard. Optional if small; otherwise skip and note it.

## Tests / evals
- Unit: chunker (one per item, stable keys, content-hash stability), FTS ranking, RRF, budget fill, low-confidence fallback, follow-up query merge, the gate (byte-identical small prompt), and lazy reindex when stale.
- Adapter: `embed()` for each OpenAI-compatible/Gemini/Ollama adapter via respx; Anthropic/Groq raise unsupported.
- Evals: run the existing grounded-answer eval set with mode=`always`; it must pass at the same rate as full mode. Add a large-profile fixture (about 40 projects, 10 jobs) with questions targeting deep items, and assert the right chunk is retrieved (lexical only; no network).
- FakeLLM only, no real network.

## Out of scope
Retrieval for chat history; reranking with an LLM; hosted multi-tenant scaling (#15); retrieval over files not in the profile.

## Gate 1 checklist
- [ ] Small profiles: prompt unchanged (test)
- [ ] Facts/identity/contact/avoid/persona always present in retrieval mode
- [ ] Lexical works offline with no new dependency; embeddings optional, owner-enabled, cost-accounted
- [ ] Retrieval miss doesn't cause false UNANSWERED (outline + fallback)
- [ ] Reindex is incremental and off the request path
- [ ] Migration 0017; no FK; bot_id on the table
- [ ] Admin Knowledge panel + per-reply chunk view
- [ ] Existing evals pass in `always` mode
