# Spec: profile-pages

**Created**: 2026-10-15
**Status**: draft
**Author**: Shivansh Mishra
**Epic**: mebot-open-source (Feature 4)

---

## Problem

The owner's data is one free-text blob. The bot can't reliably answer "how many years at X", "what's the backend of project Y", or "what are your hobbies", and the owner has no guided way to enter rich information (jobs, projects, interests). Every new project means hand-editing a big text box.

## Goal

The owner manages their data through a secured admin portal with one page per section (identity, experience, education, skills, projects, interests & hobbies, FAQ, avoid-topics, notes). The chat prompt is built from this structured data. Existing blob content is preserved as "notes".

## User Stories

- As the **owner**, I add a new project with its summary, frontend, backend, infra, my role and links, and the bot can explain it right away.
- As the **owner**, I add jobs with start/end months so later features can compute my experience exactly.
- As the **owner**, I list my hobbies and interests so the bot can talk about me as a person, not just my CV.
- As the **owner**, I add custom Q&A ("Are you open to relocation?") and topics the bot must never discuss.
- As the **owner**, I preview exactly what the bot knows before saving.

## Requirements

### Must-have
1. **Schema (Alembic 0005).** Every table: `id TEXT uuid PK`, `bot_id TEXT NOT NULL`, `created_at`, `updated_at`, `deleted_at NULL` (soft delete), index on `(bot_id, deleted_at)`. List tables also have `sort_order INTEGER NOT NULL DEFAULT 0`. No FKs.
   - `profile_identity` (one row per bot, unique `bot_id`): `full_name`, `headline`, `location`, `open_to` (e.g. "remote, relocation"), `summary`, `email_public NULL`, `phone_public NULL`, `notice_period NULL`, `salary_expectation NULL`, `work_authorization NULL`, `photo_url NULL`
   - `profile_links`: `label`, `url`
   - `experiences`: `company`, `title`, `employment_type NULL` (full-time/part-time/contract/internship/freelance), `location NULL`, `start_month TEXT` (`YYYY-MM`), `end_month TEXT NULL` (NULL = current), `description`, `highlights TEXT` (JSON array of strings), `tech TEXT` (JSON array)
   - `educations`: `institution`, `degree`, `field NULL`, `start_month`, `end_month NULL`, `grade NULL`, `description NULL`
   - `skills`: `name`, `category NULL` (language/framework/tool/cloud/soft/other), `level NULL` (beginner/intermediate/advanced/expert), `years_override REAL NULL`, `notes NULL`
   - `projects`: `name`, `tagline NULL`, `summary`, `problem NULL`, `my_role NULL`, `frontend NULL`, `backend NULL`, `infra NULL`, `data_ai NULL`, `highlights TEXT` (JSON array), `tech TEXT` (JSON array), `repo_url NULL`, `live_url NULL`, `start_month NULL`, `end_month NULL`, `status NULL` (active/completed/archived)
   - `interests`: `kind` (`hobby`|`interest`), `name`, `description NULL`
   - `faqs`: `question`, `answer`
   - `avoid_topics`: `topic`, `reply NULL` (optional polite deflection)
   - `profile_notes` (one row per bot): `content` — free text, receives the legacy blob.
2. **Legacy migration:** 0005 copies existing `profiles.content` per bot into `profile_notes.content` and pre-fills `profile_identity.full_name` from `bots.name`. Old `profiles` table kept (renamed `legacy_profiles`), not dropped. Idempotent.
3. **Admin API** (all require auth + CSRF on mutations; scoped to current bot):
   - Singletons: `GET/PUT /api/admin/profile/identity`, `GET/PUT /api/admin/profile/notes`
   - Collections, for `section ∈ {links, experiences, educations, skills, projects, interests, faqs, avoid-topics}`:
     - `GET /api/admin/profile/{section}` → `{ "items": [...] }` ordered by `sort_order`, excluding soft-deleted
     - `POST /api/admin/profile/{section}` → 201 item
     - `PUT /api/admin/profile/{section}/{id}` → item
     - `DELETE /api/admin/profile/{section}/{id}` → 204 (soft delete)
     - `PUT /api/admin/profile/{section}/order` `{ "ids": [...] }` → 204
   - `GET /api/admin/profile/preview` → `{ "text": "...", "chars": 1234, "approx_tokens": 310 }` — the exact knowledge block the chat prompt will use.
   - Remove old `GET/PUT /api/admin/profile` (blob) — replaced by notes.
   - Pydantic validation: `YYYY-MM` months, end ≥ start, URLs http(s) only, string max lengths (short fields 200, long text 5000, notes 20000), list max 200 items per section, JSON arrays of strings ≤ 30 items. Errors in the standard error shape with field details.
4. **Prompt rendering:** `prompt.render_profile(bot)` turns structured data into clean labelled sections (IDENTITY, EXPERIENCE, EDUCATION, SKILLS, PROJECTS, INTERESTS & HOBBIES, FAQ, NOTES) plus an "AVOID" list with deflections. Empty sections omitted. `/api/chat` uses it. Feature 5 will add computed facts and stricter grounding — keep the renderer a separate function so #5 can extend it.
5. **Admin UI:**
   - Admin layout with left sidebar (collapsible to top menu on mobile ≤ 768px): Dashboard (existing view), Identity, Experience, Education, Skills, Projects, Interests & Hobbies, FAQ, Avoid topics, Notes, Preview, AI Provider, Account.
   - Routes: `/admin/profile/identity`, `/admin/profile/experience`, … `/admin/profile/preview`.
   - Collection pages: list of cards, "Add" button, edit in a side panel/modal form, delete with confirm, drag-or-arrow reorder, empty state with a helpful prompt ("Add your first project — the bot will be able to explain it to recruiters").
   - Month inputs (`type="month"`), "I currently work here" checkbox clears end month, tag inputs for tech/highlights.
   - Unsaved-changes warning when leaving a dirty form.
   - Loading, empty, error (shows backend `error.message`), success toast states. Labels on all fields, keyboard accessible.
   - Preview page shows the rendered text + approximate token count with a warning above ~6k tokens (retrieval comes in #14).
   - Old profile drawer / blob editor removed.
6. **Docs:** README section "Adding your data" listing pages.

### Nice-to-have
- Duplicate an item.
- Markdown preview for long text fields.

### Out of scope
- Computed facts (years of experience) and grounding rules (#5).
- Resume / LinkedIn / GitHub import (#9, #10).
- Photo upload (URL only for now).
- Dashboard analytics (#11).

## Data Model

See Requirement 1. snake_case, plural tables, UUID text ids, UTC timestamps, soft delete via `deleted_at`, JSON arrays stored as TEXT.

## API Changes

```
GET  /api/admin/profile/identity → { "full_name": "Shivansh Mishra", "headline": "Backend engineer", ... }
PUT  /api/admin/profile/identity  { ...same fields } → 200

POST /api/admin/profile/projects
{ "name": "mebot", "summary": "Self-hostable portfolio chatbot", "frontend": "React + Vite", "backend": "FastAPI + SQLAlchemy",
  "infra": "Docker", "tech": ["Python","React"], "highlights": ["Owner adds own LLM key"], "repo_url": "https://github.com/..." }
→ 201 { "id": "…", "sort_order": 0, ...fields, "created_at": "2026-10-15T10:00:00Z", "updated_at": "…" }

PUT  /api/admin/profile/projects/order  { "ids": ["…","…"] } → 204
DELETE /api/admin/profile/experiences/{id} → 204
GET  /api/admin/profile/preview → { "text": "IDENTITY\n...", "chars": 4210, "approx_tokens": 1050 }
```
Timestamps ISO 8601 UTC with `Z`. Errors use `{ "error": { "code", "message", "status", "details": [{ "field", "message" }] } }`.

## UI Changes

New admin layout + 11 data pages + preview. Recruiter chat UI unchanged.

## Edge Cases

1. Upgrade with existing blob → appears in Notes; nothing lost; bot answers the same as before.
2. Fresh install, all sections empty → preview shows only identity name; chat still works.
3. Current job (`end_month` NULL) and multiple concurrent jobs — allowed, no overlap error.
4. End month before start → 422 with field detail.
5. Reorder with ids from another bot or missing/extra ids → 422; nothing changes.
6. Update/delete an id belonging to another bot or already deleted → 404.
7. Very long data (200 projects) → API accepts within limits; preview warns about size.
8. `javascript:` or non-http URL in links → 422.
9. Prompt injection inside owner data (e.g. FAQ answer "ignore previous instructions") — owner's own data, rendered as data inside clearly delimited sections; no special handling now (#6 covers visitor injection).
10. Two tabs editing the same item → last write wins (document; no locking).

## Testing Criteria

- Backend: migration 0005 from Feature 3 DB (blob → notes, idempotent); CRUD per section (create, list ordered, update, soft delete hides, reorder); validation errors (months, URLs, lengths, list caps); cross-bot isolation (404); auth required (401) and CSRF (403) on all routes; preview renders all sections and omits empty ones; chat prompt includes rendered profile (assert via FakeLLM received messages).
- Frontend: sidebar navigation; collection page add/edit/delete/reorder with mocked API; current-job checkbox; validation message from backend shown; empty state; unsaved-changes guard; preview page renders text + token count.
- `pytest`, `npm run typecheck && npm run build && npm test` green.

## Dependencies

- Features 1–3 (`feature/llm-provider`).
- Frontend may add a small drag-and-drop lib only if needed; arrow-button reorder is acceptable.

---

## Gate 1

- [x] Problem specific · [x] Goal measurable · [x] User stories · [x] Must/nice/out split
- [x] Tables have id + timestamps · [x] Types defined · [x] Soft delete (deleted_at)
- [x] Endpoints + examples · [x] snake_case JSON · [x] standard error shape
- [x] 10 edge cases · [x] Happy + edge tests · [x] Dependencies listed
