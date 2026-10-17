#!/usr/bin/env bash
# Dev tasks; `make <task>` calls this. Works in Git Bash on Windows and on Linux/macOS.
#   scripts/dev.sh install|dev|test|lint|fmt|build|docker|docs|docs-check
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"

py_bin() {  # venv executable path for $1 (backend|registry), then the tool name
    if [ -d "$ROOT/$1/.venv/Scripts" ]; then echo "$ROOT/$1/.venv/Scripts/$2"; else echo "$ROOT/$1/.venv/bin/$2"; fi
}
system_python() {  # skip the Windows Store "python3" stub, which only prints a hint
    for c in python3.11 python3 python py; do
        if command -v "$c" >/dev/null && "$c" -c "import sys" >/dev/null 2>&1; then command -v "$c"; return; fi
    done
    echo "no working python found" >&2; exit 1
}

venv() {  # create $1/.venv if missing and install its dev requirements
    if [ ! -d "$1/.venv" ]; then "$(system_python)" -m venv "$1/.venv"; fi
    "$(py_bin "$1" python)" -m pip install -q -r "$1/requirements-dev.txt"
}

case "${1:-help}" in
    install)
        venv backend
        venv registry
        (cd frontend && npm ci)
        ;;
    dev)
        trap 'kill 0' EXIT INT TERM
        (cd backend && "$(py_bin backend python)" -m uvicorn mebot.main:app --reload --port 8000) &
        (cd frontend && npm run dev) &
        wait
        ;;
    test)
        (cd backend && "$(py_bin backend python)" -m pytest -q -n auto -p randomly)
        (cd registry && "$(py_bin registry python)" -m pytest -q)
        (cd frontend && npm test)
        ;;
    lint)
        "$(py_bin backend python)" scripts/check_version.py >/dev/null
        (cd backend && "$(py_bin backend ruff)" check mebot tests migrations \
            && "$(py_bin backend ruff)" format --check mebot tests migrations)
        (cd registry && "$(py_bin registry ruff)" check . && "$(py_bin registry ruff)" format --check .)
        (cd frontend && npm run typecheck)
        ;;
    fmt)
        (cd backend && "$(py_bin backend ruff)" check --fix mebot tests migrations \
            && "$(py_bin backend ruff)" format mebot tests migrations)
        (cd registry && "$(py_bin registry ruff)" check --fix . && "$(py_bin registry ruff)" format .)
        ;;
    build)
        (cd frontend && npm run build)
        ;;
    docker)
        docker build -t mebot:dev .
        ;;
    docs)
        (cd backend && "$(py_bin backend python)" -m mebot.config --markdown > ../docs/configuration.md)
        ;;
    docs-check)
        (cd backend && "$(py_bin backend python)" -m mebot.config --markdown | diff -u ../docs/configuration.md -) \
            || { echo "docs/configuration.md is stale: run make docs" >&2; exit 1; }
        ;;
    *)
        sed -n '2,3p' "$0"
        exit 2
        ;;
esac
