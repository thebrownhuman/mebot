# Spec: packaging-release

**Created**: 2026-10-17
**Status**: draft
**Author**: Shivansh Mishra
**Epic**: mebot-open-source (Feature 13)

---

## Problem

Features 1–12 exist only as stacked local branches. There is no single Docker image, no CI, no license, no contributor docs, no versioned release, and several known hardening gaps (raw visitor IPs in `access_log`, react-router vulnerabilities, a slow and occasionally flaky test suite, untested Dockerfiles). A stranger cannot yet go from "found the repo" to "bot live on my server" in 10 minutes.

## Goal

Ship **mebot v0.9.0**, the first public release: one Docker image (FastAPI serving the built frontend + embed + loader), a one-command `docker compose up`, published to GHCR by CI; GitHub Actions running lint, typecheck, tests and image build on every PR; complete docs (README quickstart, per-provider guides, configuration reference, upgrade notes); MIT license, CONTRIBUTING, SECURITY, CODE_OF_CONDUCT; deploy buttons/configs for Railway, Render and Fly; and the backlog hardening items closed.

## User Stories

- As a **stranger**, I run `curl -O …/docker-compose.yml && docker compose up -d`, open `http://localhost:8080`, finish setup, and have a bot in under 10 minutes.
- As a **self-hoster on Railway/Render/Fly**, I click a deploy button / copy a config, set two env vars, and it runs with a persistent volume.
- As a **contributor**, I read CONTRIBUTING, run `make dev` / `make test`, and CI tells me if I broke something within ~10 minutes.
- As the **maintainer**, tagging `v0.9.0` builds and publishes `ghcr.io/<owner>/mebot:0.9.0` + `:latest` with release notes.

## Requirements

### Must-have
1. **Branch consolidation:** merge the stacked branches into `main` as one fast-forward/merge sequence (`feature/foundation` … `feature/install-registry`) — done by the orchestrator session, not the worker, before the build starts (worker branches from `main`). (Recorded here for traceability.)
2. **Single image** `Dockerfile` at repo root (multi-stage):
   - Stage 1 Node 22 alpine: `npm ci` + build frontend (app, embed, loader) with deterministic output paths.
   - Stage 2 Python 3.11-slim: install backend `requirements.txt` (pinned, hashes optional), copy backend + built frontend to `/app/static`; non-root user `mebot` (uid 10001); `TZ=UTC`; `PYTHONDONTWRITEBYTECODE=1`; `HEALTHCHECK` on `/api/health`; `EXPOSE 8000`; entrypoint runs `alembic upgrade head` then `uvicorn mebot.main:app --host 0.0.0.0 --port 8000 --proxy-headers` (workers = 1 — background jobs and in-memory limiters assume one process; documented).
   - FastAPI serves static files (SPA fallback for app routes, correct cache headers: hashed assets immutable 1 y, `index.html`/`embed` no-cache, `/widget/v1.js` 1 day) when `FRONTEND_DIST` set (default `/app/static` in image). The old two-container nginx setup remains as `deploy/nginx/` "advanced" example only.
   - Image size target ≤ 250 MB; `.dockerignore` excludes tests, node_modules, data, .venv, .planning.
   - `/data` volume holds DB, `secret.key`, `install.key`; image refuses to start (clear error) if `/data` not writable.
3. **Compose:** root `docker-compose.yml` using the published image (`ghcr.io/…/mebot:latest`), port `8080:8000`, `./data:/data`, `.env` optional, restart unless-stopped; `docker-compose.dev.yml` builds locally. Optional Ollama service profile (`--profile ollama`).
4. **Config reference:** `docs/configuration.md` generated from `Settings` (script `python -m mebot.config --markdown`, checked in CI that the doc is up to date). `.env.example` complete and grouped.
5. **CI (GitHub Actions)** `.github/workflows/ci.yml` on PR + push to main:
   - backend: ruff check + format check, pytest with `pytest-xdist -n auto` (add `pytest-xdist` dev dep; make tests xdist-safe: per-worker temp DB/data dirs) — target < 5 min; `--reruns 0` (no auto-retry hiding flakes).
   - registry: ruff + pytest.
   - frontend: `npm ci`, typecheck, build, test (incl. size check), `npm audit --omit=dev --audit-level=high` (fail on high/critical prod vulns).
   - docker: build root image (no push) + `docker run` smoke: start container, wait for healthy, `GET /api/health`, `GET /api/setup/status` → `setup_required: true`, `GET /widget/v1.js` 200.
   - registry docker build smoke.
   - Concurrency cancel-in-progress; pip/npm caching.
   - `.github/workflows/release.yml` on tag `v*`: build multi-arch (amd64, arm64) with buildx, push `ghcr.io/<owner>/mebot:{version,latest}` and `…/mebot-registry:{version,latest}`, generate GitHub Release with notes from `CHANGELOG.md` section. Owner placeholder: `${{ github.repository_owner }}` (repo URL still TBD — no hardcoded owner).
   - Dependabot config for pip, npm, GitHub Actions (weekly, grouped minor/patch).
6. **Version:** `mebot.__version__ = "0.9.0"`, frontend `package.json` version synced (CI check), shown in admin footer + `/api/health`. `CHANGELOG.md` (Keep a Changelog) with a 0.9.0 entry summarising features 1–12.
7. **Hardening backlog (close all):**
   - **Hash visitor IPs** in `access_log` and anywhere else raw IPs are stored (sessions?) with HMAC-SHA256(SECRET_KEY, ip) truncated (same helper as #6 usage_counters). Alembic 0016 rewrites existing rows (hash in place) and drops/renames raw columns as needed. Rate limiting keeps using the raw IP in memory only. Admin views show hash prefix. README privacy section updated.
   - **react-router** (and any prod dependency) vulnerabilities fixed (`npm audit fix` / version bump), CI gate added.
   - **Flaky test hunt:** run the full suite 5× with `-p randomly` style ordering (add `pytest-randomly` dev dep) and under `-n auto`; fix any order/timing-dependent test found (inject clocks, no wall-clock asserts); record result in PR notes.
   - **Suite speed:** profile with `--durations=25`; reduce top offenders (shared app fixture per module where safe, cheaper password hashing params in tests via settings override, avoid real sleeps).
   - **Embed contact panel** light-theme styling (follows widget theme tokens).
   - Registry Dockerfile actually built and smoke-tested in CI.
8. **Platform deploy configs:**
   - `deploy/railway/railway.json` (Dockerfile build, volume `/data`, healthcheck `/api/health`).
   - `render.yaml` (web service from image, disk at `/data`, env vars with `generateValue: true` for `SECRET_KEY`).
   - `fly.toml` (volume mount `/data`, `internal_port = 8000`, health check, single machine).
   - README deploy buttons for Railway and Render (button URLs use a placeholder `<repo-url>` token replaced by a one-line note until the repo URL exists).
   - `docs/deploy/homelab.md`: Docker compose + Cloudflare Tunnel/Caddy example, backups of `/data`.
9. **Docs** (`README.md` restructured + `docs/`):
   - README: what it is (GIF/screenshot placeholders under `docs/assets/`), 10-minute quickstart, features list, "Add your API key" (links per provider), embed snippet, Telegram, privacy & telemetry summary, upgrade, links to docs.
   - `docs/`: configuration, providers (OpenRouter, Gemini, OpenAI, Anthropic, Groq, Ollama, custom), telegram, widget, imports, learning loop, dashboard & data, telemetry, security model (what's encrypted, what's hashed, threat model summary), upgrading (backup `/data`, migrations run automatically, downgrade not supported), troubleshooting, FAQ.
   - Consolidate the per-feature README sections written in #1–#12 into these docs (no duplication; README links out).
10. **Community files:** `LICENSE` (MIT, © 2026 Shivansh Mishra), `CONTRIBUTING.md` (dev setup, `make` targets, TDD expectation, commit style, PR checklist), `SECURITY.md` (private disclosure via email/GitHub advisories, supported versions), `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), issue templates (bug, feature), PR template.
11. **Dev ergonomics:** root `Makefile` (or `justfile`) with `dev` (backend + frontend hot reload), `test`, `lint`, `fmt`, `build`, `docker`, `docs-check`; works in Git Bash on Windows and on Linux/macOS.

### Nice-to-have
- `docs/` rendered with MkDocs Material and published via GitHub Pages.
- Signed images (cosign) + SBOM.

### Out of scope
- Hosted mode (#15), paid plans (#16), retrieval (#14).
- Helm chart / Kubernetes manifests.

## Data Model

Alembic 0016: hash raw IP values in `access_log.ip` (and any other raw-IP column found) in place using the #6 helper; rename to `ip_hash` if the column name says `ip`. No new tables.

## API Changes

`GET /api/health` adds `"version": "0.9.0"`. Admin views expose `ip_hash` prefix instead of `ip`. No other API changes.

## UI Changes

Admin footer shows version; IP displays become hash prefixes; embed contact panel follows theme.

## Edge Cases

1. Upgrading an existing two-container compose install → docs give exact steps (stop, back up `data/`, switch to new compose, same volume path) — data dir layout identical.
2. `/data` mounted read-only or owned by root on Linux → clear startup error with `chown 10001` hint.
3. ARM homelab (Raspberry Pi) → arm64 image works (buildx in release workflow; smoke on amd64 in CI).
4. Running with `--workers 2` → startup warning: background jobs/limits assume one process; docs explain.
5. Migration 0016 on a large access_log → batched updates (1k rows) to avoid long locks.
6. Platform without persistent disk (Render free) → docs warn data loss on restart; recommend disk.
7. `npm audit` high vuln appears in a transitive dev dep → only prod deps gate CI (`--omit=dev`).
8. Docs check fails because a setting was added without docs → CI fails with diff.
9. Tag pushed with version mismatch between `__version__`, package.json and tag → release workflow fails early.
10. Flaky test found but root cause outside scope → fix or quarantine with an issue reference; never silently retry.

## Testing Criteria

- Image: CI smoke (health, setup status, widget loader, SPA fallback route `/admin` returns index.html, static asset cache headers); non-root user; `/data` not writable → exits non-zero with message.
- Static serving unit tests (cache headers per path class, SPA fallback doesn't swallow `/api/*` 404s).
- Migration 0016: raw IPs hashed, idempotent, batched; no raw IP remains anywhere in DB after upgrade (test scans tables).
- Config doc generator matches checked-in doc.
- Version sync check.
- Suite: passes 5× randomised order + under xdist; total CI backend job < 5 min (report actual).
- `npm audit --omit=dev --audit-level=high` clean.
- Frontend: embed contact panel light theme snapshot/class test.
- All existing suites green: `pytest` (mebot + registry), `npm run typecheck && npm run build && npm test`.

## Dependencies

- Features 1–12 merged to `main`.
- Dev deps: `pytest-xdist`, `pytest-randomly`. No runtime deps added.
- Docker daemon locally for the image build/smoke (if unavailable locally, CI is the gate — worker must say so).

---

## Gate 1

- [x] Problem specific · [x] Goal measurable · [x] User stories · [x] Must/nice/out split
- [x] Migration defined · [x] Types n/a · [x] Delete strategy n/a (in-place hashing)
- [x] API changes listed · [x] snake_case JSON
- [x] 10 edge cases · [x] Happy + edge tests · [x] Dependencies listed
