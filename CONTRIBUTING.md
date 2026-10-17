# Contributing

Thanks for helping. Bug reports, docs fixes and focused pull requests are all welcome. For a
bigger change, open an issue first so we can agree on the approach.

## Dev setup

You need Python 3.11, Node 22 and GNU make (Linux/macOS have it; on Windows use Git Bash,
where `make` comes with the Git for Windows SDK, or run the commands in the `Makefile` by
hand).

```bash
make install    # backend venv + dev deps, frontend npm ci, registry venv
make dev        # backend on :8000 with reload + Vite on :5173 (Ctrl-C stops both)
```

Open http://localhost:5173 and go through setup. Data goes to `backend/data/` (git-ignored).

| Target | What it does |
|---|---|
| `make test` | backend (parallel, random order), registry and frontend tests |
| `make lint` | ruff check + format check, TypeScript typecheck |
| `make fmt` | ruff format + fix |
| `make build` | frontend production build |
| `make docker` | build the image as `mebot:dev` |
| `make docs-check` | fail if `docs/configuration.md` is stale (`make docs` regenerates it) |

## Expectations

- **Tests first.** Write the failing test, then the code. Every behaviour change comes with
  a test; bug fixes come with a test that failed before the fix.
- **No flaky tests.** The backend suite runs in random order across workers in CI with no
  reruns. Inject clocks instead of sleeping, use `tmp_path` instead of fixed paths, and never
  call the network (use `respx`; `conftest.py` has a fake LLM).
- **No raw IPs, keys or tokens** in the database, logs or error messages.
- **Migrations** go in `backend/migrations/versions/` with the next number, are forward-only
  and get a test.
- **New settings** need a comment above the field in `mebot/config.py`; then run `make docs`.
- UI changes work at 375, 768 and 1440 px wide and have loading, empty and error states.

## Commits and pull requests

[Conventional commits](https://www.conventionalcommits.org/): `feat(scope): …`, `fix: …`,
`docs: …`, `test: …`, `build: …`. One logical change per commit; say *why* in the body when
it isn't obvious.

Before opening a PR, check:

- [ ] `make lint` and `make test` pass
- [ ] new behaviour has tests
- [ ] docs updated (README / `docs/`), `CHANGELOG.md` entry under *Unreleased*
- [ ] no secrets, `.db` files, `secret.key`, `install.key` or `.env` committed

CI runs all of this plus a Docker build and smoke test on every PR.

## Releases (maintainers)

Bump `backend/mebot/__init__.py` and `frontend/package.json` together
(`python scripts/check_version.py` checks), move *Unreleased* in `CHANGELOG.md` to the new
version, and push a `vX.Y.Z` tag. The release workflow refuses a tag that doesn't match,
builds amd64 + arm64 images, pushes them to GHCR and creates the GitHub release from the
changelog section.
