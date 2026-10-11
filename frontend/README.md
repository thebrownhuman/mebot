# me-bot terminal — React + Vite + TS + R3F

Two portals, one app:
  /talkaboutshivansh            recruiter portal — welcome popup + chat only
  /talkaboutshivansh/aaddmmiinn admin portal — password-gated; profile + sessions + log

## Run
  ollama serve
  # backend (separate folder):
  cd ../backend && pip install -r requirements.txt
  set OLLAMA_HOST=http://127.0.0.1:11434   (Windows; avoids IPv6 localhost issue)
  uvicorn app:app --reload --port 8000
  # frontend:
  npm install
  npm run typecheck
  npm run dev
  # open http://localhost:5173/talkaboutshivansh

## Portals
- Recruiter (/talkaboutshivansh): a popup greets them as Anya, asks their name
  (logged to the session); a login-credentials field is shown but disabled. Then
  they chat. No profile or admin controls are visible.
- Admin (/talkaboutshivansh/aaddmmiinn): passphrase gate, then chat plus the
  profile editor, session browser, and access log.

## Admin password
Set in src/pages/AdminPage.tsx -> ADMIN_PASS (default "shivansh"). NOTE: this is a
client-side gate — it hides the panel from casual visitors but is NOT real security
(the check runs in the browser, so the password ships in the JS bundle). For a true
public deployment, move auth to the backend. Fine for local / link-sharing use.

## The thinking indicator
While the model generates, the reply line shows a Claude-Code-style status:
a cycling glyph, a rotating verb (Thinking / Composing / Recalling…), and an
elapsed-seconds counter. It's replaced by the streamed answer once tokens arrive.

## Notes
- think:false stays in the backend; the frontend never calls Ollama directly.
- The scroll bug is fixed (flex child has min-h-0 so the transcript scrolls inside
  its pane instead of overflowing the layout).
- SPA routing: Vite handles deep links in dev; nginx.conf has try_files for Docker.
