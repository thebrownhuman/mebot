# mebot frontend — React + Vite + TS + R3F

Two routes, one app:

    /        public chat — welcome popup + chat only
    /admin   admin — passphrase-gated; profile + sessions + log
    *        redirects to /

## Run

    npm install
    npm run dev        # proxies /api to http://localhost:8000 (start ../backend first)
    # open http://localhost:5173

## Check

    npm run typecheck
    npm run build
    npm test           # Vitest + Testing Library

## Admin passphrase

Set `VITE_ADMIN_PASS` at build time (default `admin`). This is a client-side gate
only — the value ships in the JS bundle. Real backend auth is planned.

## Notes
- The frontend never calls Ollama directly; `think: false` is enforced in the backend.
- SPA routing: Vite handles deep links in dev; `nginx.conf` has `try_files` for Docker.
