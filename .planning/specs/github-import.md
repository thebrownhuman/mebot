# Spec: github-import

**Created**: 2026-10-17
**Status**: draft
**Author**: Shivansh Mishra
**Epic**: mebot-open-source (Feature 10)

---

## Problem

Projects are what recruiters ask about most ("What's the backend of X?", "What did you build with React?"), but writing a full project entry (summary, frontend, backend, infra, tech, highlights) for every repo is tedious. The owner's projects already live on GitHub with READMEs and manifests that describe them.

## Goal

The owner pastes a repo URL (or their GitHub username and picks repos) and gets a ready-to-review project entry per repo — summary, stack split into frontend/backend/infra/data-AI, tech list, highlights, links, dates — through the same review/apply flow as Feature 9. Tech is detected deterministically from manifests; the LLM only writes prose grounded in the README.

## User Stories

- As the **owner**, I paste `https://github.com/shivansh/mebot`, review the drafted project, fix one line, click Apply — the bot can now explain mebot's frontend and backend.
- As the **owner**, I enter my username, tick my 6 best repos, and import them all in one review.
- As the **owner**, re-importing a repo I already have proposes only changes (new tech, updated summary).

## Requirements

### Must-have
1. **Reuse Feature 9:** `import_jobs.kind = 'github'`, same draft/match/apply/discard endpoints, review UI and expiry. Draft sections: `projects` (one item per repo) + optional `skills` proposals.
2. **Inputs:**
   - `POST /api/admin/import/github` `{ "repo_urls": ["https://github.com/owner/repo", …] }` (1–10) → 202 job.
   - `GET /api/admin/import/github/repos?username=…` → public, non-fork, non-archived-first repos sorted by stars then `pushed_at` (max 100): `{ name, full_name, description, language, stars, pushed_at, fork, archived }` for the picker.
   - URL parsing strict: `https://github.com/{owner}/{repo}` (optional `.git`, trailing slash, `/tree/...` stripped); owner/repo `^[A-Za-z0-9-_.]{1,100}$`. Anything else → 422.
3. **GitHub client** `mebot/imports/github.py` (httpx, `https://api.github.com` only — **no other host is ever fetched**, including links found in READMEs):
   - Endpoints: `GET /repos/{o}/{r}`, `/repos/{o}/{r}/languages`, `/repos/{o}/{r}/readme` (base64 content, cap 30k chars after decode), `/repos/{o}/{r}/git/trees/{default_branch}` (non-recursive root + one level into common dirs `frontend/ backend/ client/ server/ web/ api/ apps/ packages/`), `/repos/{o}/{r}/contents/{path}` for allow-listed manifests ≤ 200 KB each, ≤ 15 files per repo, `/users/{u}/repos?type=owner&per_page=100`.
   - Optional token: env `GITHUB_TOKEN` or an admin-entered token (encrypted like #3, `Authorization: Bearer`); used only for rate limits on public data. Token never logged/returned.
   - Rate limit: 403/429 with `X-RateLimit-Remaining: 0` → `failed` `GITHUB_RATE_LIMITED` with reset time + hint to add a token. 404 → `REPO_NOT_FOUND` (private or missing; private repos out of scope). Timeouts 10 s per call, 90 s per job.
4. **Manifest allow-list:** `package.json`, `requirements*.txt`, `pyproject.toml`, `Pipfile`, `go.mod`, `Cargo.toml`, `pom.xml`, `build.gradle(.kts)`, `composer.json`, `Gemfile`, `pubspec.yaml`, `Dockerfile`, `docker-compose*.yml`, `vercel.json`, `netlify.toml`, `fly.toml`, `railway.toml`, `*.tf` (names only), `.github/workflows/*.yml` (names only), `prisma/schema.prisma`, `angular.json`, `next.config.*`, `vite.config.*`, `tailwind.config.*`.
5. **Deterministic tech detection** `mebot/imports/techmap.py`: dependency/name → `{ tech, layer }` table (layer ∈ frontend|backend|infra|data_ai|tooling), e.g. react/next/vue/svelte/angular/tailwind/three → frontend; express/fastapi/django/flask/spring-boot/gin/nestjs/sqlalchemy/prisma → backend; docker/terraform/github-actions/vercel/netlify/fly/railway/k8s → infra; torch/tensorflow/scikit-learn/langchain/openai/anthropic/pandas → data_ai; postgres/mysql/mongodb/redis drivers → backend (database). ≥ 80 entries, case-insensitive, scoped packages handled. GitHub `languages` (≥ 5% bytes) added as languages. Output: per-layer tech lists + evidence (file + key).
6. **LLM drafting** (owner's provider, one call per repo, strict pydantic JSON): `summary` (≤ 400 chars), `problem`, `my_role` (null unless README states it), `frontend`, `backend`, `infra`, `data_ai` (short prose each, null if layer empty), `highlights` (≤ 5, ≤ 120 chars each). Inputs: repo metadata, detected tech per layer, README text. Rules: use only README + detected tech; README is **data, not instructions** (wrapped in delimiters; injection phrases neutralised); no metrics/numbers not in the README.
   - Grounding: numbers in output must appear in README; tech names mentioned in prose must be in detected tech or README; failures → `needs_review` with reason.
   - Personal-category text (#7b) stripped.
   - No LLM configured → draft still created from metadata + tech (summary = repo description), flagged "AI summary unavailable".
7. **Deterministic fields:** `name` (repo name humanised, editable), `tagline` = description, `tech` = all detected, `repo_url`, `live_url` = `homepage` (http(s) only), `start_month` = `created_at`, `end_month` = null unless `archived` (then `pushed_at` month), `status` = archived→`archived`, pushed within 6 months→`active`, else `completed`.
8. **Matching (#9 extension):** project by `repo_url` (normalised) first, then name; `changed` shows field diffs. Skill proposals: detected tech not already a skill → `new` items defaulting to **skip** (owner ticks what they want).
9. **Admin UI:** Import page gets a third card "GitHub". Tabs: "Repo URL(s)" (textarea, one per line, validated client-side) and "From username" (fetch list → checkbox picker with stars/language/last push, select up to 10). Optional "GitHub token (for rate limits)" field in a collapsible, masked after save. Review screen per #9, with per-project "Evidence" toggle listing which file detected each tech.
10. **Docs:** README "Import projects from GitHub" (public repos, rate limits, token scope: none/public read only).

### Nice-to-have
- "Refresh from GitHub" button on a project imported from a repo.
- Import pinned repos (needs GraphQL + token).

### Out of scope
- Private repos / OAuth app.
- GitLab/Bitbucket.
- Reading source code beyond the manifest allow-list.

## Data Model

No new tables: reuses `import_jobs` (`kind='github'`). Alembic 0013 adds `github_token_encrypted TEXT NULL`, `github_token_last4 TEXT NULL` to `llm_configs`' sibling table — implement as new single-row table `integration_tokens` (`id`, `bot_id`, `provider`='github', `token_encrypted`, `token_last4`, `created_at`, `updated_at`; unique `(bot_id, provider)`).

## API Changes

```
GET  /api/admin/import/github/repos?username=shivansh → { "items": [{ "full_name": "shivansh/mebot", "description": "…", "language": "Python", "stars": 12, "pushed_at": "2026-10-16T…Z", "fork": false, "archived": false }] }
POST /api/admin/import/github { "repo_urls": ["https://github.com/shivansh/mebot"] } → 202 { "id": "…", "status": "processing" }
PUT  /api/admin/integrations/github { "token": "ghp_…" } → { "token_last4": "…" }   DELETE → 204
GET  /api/admin/import/jobs/{id} → draft.sections.projects[0].data = { "name": "mebot", "summary": "…", "frontend": "React + Vite …",
       "backend": "FastAPI + SQLAlchemy …", "infra": "Docker, nginx", "tech": ["Python","FastAPI","React","Vite","Docker"],
       "repo_url": "https://github.com/shivansh/mebot", "start_month": "2026-07", "status": "active" },
     evidence: [{ "tech": "FastAPI", "file": "backend/requirements.txt" }]
```
Error codes: `INVALID_REPO_URL`, `REPO_NOT_FOUND`, `GITHUB_RATE_LIMITED`, `GITHUB_UNAVAILABLE`, `TOO_MANY_REPOS`.

## UI Changes

GitHub card on Import page (URL + username tabs, repo picker, optional token), evidence toggle in review.

## Edge Cases

1. Private or missing repo → `REPO_NOT_FOUND` for that repo; others in the job still processed (per-repo error in draft).
2. Unauthenticated rate limit (60/h) hit → clear message + reset time + token hint.
3. No README → summary from description + tech; flagged.
4. Huge README / monorepo with many manifests → caps (30k chars, 15 files, 2 levels) applied.
5. README contains "ignore previous instructions…" → treated as data; output schema-constrained; grounding check.
6. README links to external sites → never fetched.
7. Fork repos hidden in username picker (toggle to show).
8. `homepage` not http(s) → dropped.
9. Same repo listed twice / already imported → deduped / `same`/`changed`.
10. Malformed manifest (invalid JSON/TOML) → skipped with evidence note, no crash.
11. Username not found → 404 `REPO_NOT_FOUND`-style `USER_NOT_FOUND`.
12. No LLM config → deterministic draft still works.

## Testing Criteria

- URL parsing table (valid/invalid/tree paths/.git).
- Client via respx: each endpoint, base64 README decode + cap, tree depth limits, manifest allow-list (assert non-listed paths never requested), only api.github.com requested, token header when set, rate-limit/404/timeout mapping, token never in logs/errors.
- Techmap: per-ecosystem fixtures (package.json, requirements, pyproject, go.mod, Cargo, pom, gradle, docker-compose), scoped packages, languages ≥5%.
- Drafting with FakeLLM: valid JSON, grounding flags (invented metric, unknown tech), injection README, personal text stripped, no-LLM fallback.
- Deterministic fields: dates/status rules.
- Matching by repo_url/name; skill proposals default skip.
- Multi-repo job with one failing repo.
- Frontend: URL tab validation, username picker (max 10), token field, evidence toggle.
- `pytest`, `npm run typecheck && npm run build && npm test` green.

## Dependencies

- Feature 9 (`feature/imports`) — must be built first.
- Python: `tomli` only if Python < 3.11 (use stdlib `tomllib`); no other deps.

---

## Gate 1

- [x] Problem specific · [x] Goal measurable · [x] User stories · [x] Must/nice/out split
- [x] New table has id + timestamps · [x] Types defined · [x] Reuse of import_jobs stated
- [x] Endpoints + examples · [x] snake_case JSON · [x] standard error codes
- [x] 12 edge cases · [x] Happy + edge tests · [x] Dependencies listed
