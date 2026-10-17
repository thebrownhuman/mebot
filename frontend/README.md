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

## Auth

There is no client-side secret. The app asks the backend on boot whether first-run
setup is pending (`/setup`), `/admin` is guarded by `GET /api/auth/me`, and the API
client (`src/lib/api.ts`) sends cookies plus an `X-CSRF-Token` header on writes.

## Notes
- The frontend never calls an LLM provider directly; API keys go to the backend once
  (setup / AI Provider page) and are never sent back.
- SPA routing: Vite handles deep links in dev; the backend falls back to `index.html` for app routes in the Docker image (`mebot/static.py`).
