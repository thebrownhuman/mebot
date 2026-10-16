# Spec: imports

**Created**: 2026-10-17
**Status**: draft
**Author**: Shivansh Mishra
**Epic**: mebot-open-source (Feature 9)

---

## Problem

Filling ten admin pages by hand (jobs, education, skills, projects…) is the biggest barrier for a new owner. Almost everyone already has a resume (PDF/DOCX) and a LinkedIn profile. The owner should be able to upload those and get their profile filled in minutes — reviewing everything before it's saved, so nothing wrong or invented enters the bot's knowledge.

## Goal

From Admin → Import, the owner uploads a resume (PDF/DOCX) or a LinkedIn data-export ZIP, sees every extracted item side by side with what's already in their profile, accepts/edits/skips each one, and applies them in one go. LinkedIn import is deterministic and works without an LLM key; resume import uses the owner's provider with hallucination checks. Uploaded files are never stored.

## User Stories

- As a **new owner**, I upload my resume PDF and in under a minute see my jobs, education, skills and projects ready to review; I accept most, fix a date, skip one, and click Apply.
- As an **owner**, I download "Get a copy of your data" from LinkedIn, upload the ZIP, and my positions/education/skills import exactly, with no AI involved.
- As an **existing owner**, I re-import an updated resume and only new or changed items are proposed; existing ones are matched, not duplicated.
- As an **owner**, I trust that my file isn't kept on the server and that LinkedIn messages/connections are never read.

## Requirements

### Must-have
1. **Schema (Alembic 0012)** `import_jobs`: `id`, `bot_id`, `kind` (`resume`|`linkedin`), `status` (`processing`|`ready`|`applied`|`failed`|`expired`), `filename` (sanitised, ≤ 200 chars), `sha256`, `size_bytes`, `draft TEXT NULL` (JSON), `source_text TEXT NULL` (resume only; for review highlighting), `error_code NULL`, `error_message NULL`, `applied_summary TEXT NULL` (JSON counts), `created_at`, `updated_at`, `expires_at` (created + 7 days). Expired jobs purged (draft + source_text nulled, row kept as `expired`) on startup/daily.
2. **Upload rules** `POST /api/admin/import/{kind}` (multipart, auth + CSRF):
   - Size: resume ≤ 10 MB, LinkedIn ZIP ≤ 50 MB (enforced while streaming, 413 beyond).
   - Type by **magic bytes**, not extension: PDF `%PDF-`, DOCX/ZIP `PK\x03\x04` + `[Content_Types].xml` with WordprocessingML main part. Reject `.docm`/macro-enabled (`vnd.ms-word.document.macroEnabled`), encrypted PDFs, legacy `.doc` → 415 with guidance.
   - Files processed **in memory** (or a temp file deleted in `finally`); never written to `data/`, never logged.
   - Rate limit 10 imports/hour per bot (via #6 limiter); one `processing` job per bot at a time (409).
   - Same `sha256` already `ready` → return that job instead of reprocessing.
3. **Resume pipeline** (`mebot/imports/resume.py`, background task, 120 s timeout):
   - Text extraction: PDF via `pypdf` (layout-ish text, page order); DOCX via `python-docx` (paragraphs + tables). < 200 chars of text → `failed` `NO_TEXT` ("Looks like a scanned PDF — try the DOCX or LinkedIn import").
   - LLM structured extraction with the owner's provider (#3) into a strict pydantic schema mirroring #4 sections: identity (full_name, headline, location, summary), experiences, educations, skills (name, category), projects (name, summary, tech, links, dates), interests, contact channels (email, LinkedIn/GitHub/portfolio URLs — **phone numbers dropped**). Prompt: extract only what's written, months as `YYYY-MM`, unknown → null, no inference.
   - Long text (> 12k chars) split by detected section headings, extracted per chunk, merged.
   - Invalid JSON → one repair retry, then `failed` `EXTRACTION_FAILED`.
   - **Grounding check:** each item's key strings (company, title, institution, degree, project name, skill name) must appear in the source text (case/whitespace-insensitive, fuzzy ratio ≥ 0.85); each date's year must appear. Failing items kept but flagged `needs_review: true` with reason.
   - Personal-category data (#7b filter: date of birth, marital status, religion, etc.) stripped from the draft.
4. **LinkedIn pipeline** (`mebot/imports/linkedin.py`, deterministic, no LLM):
   - Open ZIP without extracting to disk; reject path traversal names; limits: ≤ 1000 entries, ≤ 200 MB total uncompressed, per-entry ratio ≤ 100× (zip-bomb guard).
   - Read **only** an allow-list: `Profile.csv`, `Positions.csv`, `Education.csv`, `Skills.csv`, `Projects.csv`, `Certifications.csv`, `Languages.csv`, `Honors.csv`, `Email Addresses.csv`. Everything else (messages, connections, invitations, ads, phone numbers…) is never opened. Find files case-insensitively at any folder depth.
   - Tolerant CSV: UTF-8 with/without BOM, header matching case/space-insensitive, skip LinkedIn "Notes:" preamble lines before the header.
   - Dates: `Jan 2020`, `January 2020`, `2020`, `2020-01`, `01/2020` → `YYYY-MM` (year-only → `YYYY-01` flagged approximate); empty Finished On → current.
   - Mapping: Profile → identity (name, headline, summary, location); Positions → experiences; Education → educations (degree, field from Notes if obvious); Skills → skills; Projects → projects; Certifications → educations with degree = certification name, institution = authority (flag `kind: certification` in draft, shown separately in review); Languages → skills category `language`; Honors → interests? No — → `profile_notes` append proposal; Email Addresses → email channel proposal (unticked by default if > 1 address, primary pre-selected).
5. **Draft format** (both kinds): `{ sections: { identity: {...}, experiences: [ { temp_id, data, match: { status: "new"|"same"|"changed", existing_id?, diff? }, needs_review, reason? } ], ... } }`.
   - **Matching** against current profile: experience by normalised company + title + start_month (±1 month); education by institution + degree; skill by name (aliases from #5); project by name; channel by kind + value; identity field-by-field. `same` items default to skip, `changed` default to "update", `new` default to "add".
6. **Apply** `POST /api/admin/import/jobs/{id}/apply` `{ decisions: [{ temp_id, action: "add"|"update"|"skip", data? }] }` — validates each `data` with #4 schemas, applies all in **one transaction**, identity fields only overwritten when action `update` chosen per field, sets `applied`, stores counts. Re-applying an applied job → 409.
7. **Other endpoints:** `GET /api/admin/import/jobs` (latest 20), `GET /api/admin/import/jobs/{id}` (status + draft for review), `DELETE /api/admin/import/jobs/{id}` (discard → draft/source wiped).
8. **Admin UI "Import" page** (sidebar):
   - Two cards: Resume (PDF/DOCX) and LinkedIn export, with a short "How to get your LinkedIn data" guide (Settings → Data privacy → Get a copy of your data → pick Positions, Profile, Education, Skills, Projects… → wait for email → upload ZIP). Privacy note: "Your file isn't stored. We never read your LinkedIn messages or connections."
   - Drag-and-drop + file picker, client-side size/extension pre-check, upload progress, then processing status (poll every 2 s).
   - **Review screen:** grouped by section; each item card shows proposed data, match badge (New / Already in profile / Changed with field-level diff), needs-review warning with reason, controls Add/Update/Skip + inline edit; "Accept all new" bulk action; for resume imports a "Show in source" toggle highlighting the matched text snippet.
   - Apply → summary ("Added 4 jobs, 2 projects, 11 skills; updated 1") with links to the sections. Discard button.
   - Resume card disabled with hint if no working LLM config.
9. **Docs:** README "Import your resume or LinkedIn".

### Nice-to-have
- LLM-assisted splitting of LinkedIn position descriptions into highlights (opt-in).
- Import history page with re-open of applied drafts.

### Out of scope
- GitHub import (#10).
- OCR for scanned PDFs.
- Scraping LinkedIn profiles or any LinkedIn API.
- Storing original files.

## Data Model

Alembic 0012 `import_jobs` (req 1). snake_case, UUID ids, UTC timestamps; expiry nulls content (documented), rows deleted by owner via discard.

## API Changes

```
POST /api/admin/import/resume   (multipart file) → 202 { "id": "…", "status": "processing" } | 413 | 415 | 409 | 429
POST /api/admin/import/linkedin (multipart file) → 202 { "id": "…", "status": "processing" }
GET  /api/admin/import/jobs/{id} → { "id": "…", "kind": "linkedin", "status": "ready",
  "draft": { "sections": { "experiences": [ { "temp_id": "e1", "data": { "company": "Acme", "title": "Backend Engineer",
      "start_month": "2024-02", "end_month": null, "description": "…" },
      "match": { "status": "new" }, "needs_review": false } ] } } }
POST /api/admin/import/jobs/{id}/apply { "decisions": [ { "temp_id": "e1", "action": "add" }, { "temp_id": "s4", "action": "skip" } ] }
  → 200 { "applied": { "experiences": { "added": 1, "updated": 0 }, "skills": { "added": 10 } } }
DELETE /api/admin/import/jobs/{id} → 204
```
Errors: standard shape; codes `FILE_TOO_LARGE`, `UNSUPPORTED_FILE`, `ENCRYPTED_PDF`, `NO_TEXT`, `EXTRACTION_FAILED`, `IMPORT_IN_PROGRESS`, `LLM_NOT_CONFIGURED`, `ZIP_UNSAFE`, `NO_LINKEDIN_FILES`.

## UI Changes

New Import page with upload, processing and review states; sidebar entry.

## Edge Cases

1. Scanned/image-only PDF → `NO_TEXT` with suggestion.
2. Password-protected PDF → `ENCRYPTED_PDF`.
3. `.doc` / `.docm` / renamed `.exe` as `.pdf` → 415 by magic bytes.
4. Zip bomb / path traversal / 5000-entry ZIP → `ZIP_UNSAFE`, nothing read beyond limits.
5. LinkedIn ZIP without any allow-listed files (e.g. only messages) → `NO_LINKEDIN_FILES`.
6. LinkedIn CSV with BOM, "Notes:" preamble, different header casing → parsed.
7. LLM invents a company not in the resume → `needs_review` with reason; default action still "add" only if owner confirms (needs_review items default to Skip).
8. Re-import same resume → same job returned (sha256); updated resume → existing items `same`/`changed`.
9. Resume contains phone number / DOB → dropped from draft.
10. Two uploads at once → second 409.
11. LLM timeout mid-extraction → `failed` with retry button; no partial apply.
12. Apply with edited data failing validation (end before start) → 422 for that item, nothing applied.
13. Job expired (7 days) → review shows "expired, upload again".

## Testing Criteria

- Upload: size streaming limit, magic-byte detection (pdf/docx/zip/docm/doc/exe), encrypted PDF, rate limit, one-at-a-time, sha256 dedupe, file never written outside temp (assert data dir unchanged) and not logged.
- Resume: PDF + DOCX fixtures generated in tests; extraction with FakeLLM returning valid/invalid/repairable JSON; chunking; grounding check flags invented items; personal data and phones stripped; timeout → failed.
- LinkedIn: fixture ZIPs built in tests (BOM, preamble, header variants, nested folder); date parsing table; mapping per file; allow-list (assert non-listed entries never opened — spy); zip-bomb/traversal/entry-count guards.
- Matching: new/same/changed per section incl. aliases and ±1 month.
- Apply: transaction (one invalid → nothing applied), identity per-field update, re-apply 409, counts.
- Expiry purge.
- Frontend: upload flow states, review cards (badges, diff, needs-review default skip, bulk accept, edit), apply summary, discard, resume disabled without LLM.
- `pytest`, `npm run typecheck && npm run build && npm test` green.

## Dependencies

- Features 1–8 (`feature/embed-widget`).
- Python: `pypdf`, `python-docx`, `python-multipart` (if not present). Pure-Python, no system packages.

---

## Gate 1

- [x] Problem specific · [x] Goal measurable · [x] User stories · [x] Must/nice/out split
- [x] Table has id + timestamps · [x] Types defined · [x] Expiry/discard strategy stated
- [x] Endpoints + examples · [x] snake_case JSON · [x] standard error shape + codes
- [x] 13 edge cases · [x] Happy + edge tests · [x] Dependencies listed
