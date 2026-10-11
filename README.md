# mebot — candidate terminal (full project)

Three parts, side by side:

  mebot-app/      Python FastAPI backend + SQLite (the brain + storage)
  mebot-react/    React + Vite + TypeScript frontend with 3D reactive orb
  mebot-stack/    docker-compose to run both together

Keep these three folders as siblings — docker-compose.yml references the other
two by relative path.

## Run bare-metal (best for development, hot-reload)

  # terminal 1
  ollama serve

  # terminal 2
  cd mebot-app/backend
  pip install -r requirements.txt
  uvicorn app:app --reload --port 8000

  # terminal 3
  cd mebot-react
  npm install
  npm run typecheck     # run once to confirm it compiles
  npm run dev
  # open the URL Vite prints (http://localhost:5173)

## Run with Docker (one command)

  ollama serve          # keep Ollama on the host for GPU
  cd mebot-stack
  docker compose up --build
  # open http://localhost:8080

## Using it
Open the app, click "profile", paste your real details, save, then chat as the
recruiter. The orb idles teal, goes amber+spinning while thinking, and pulses
green as it answers. "admin" shows the access log + session stats from the db.
"sessions" reopens past conversations.

## Notes
- think:false lives in the backend (mebot-app/backend/app.py). The frontend never
  talks to Ollama directly, so the reasoning-leak can't come back through the UI.
- The data/ folders hold the SQLite db. Empty on first download (just .gitkeep);
  the db file is created on first run.
- node_modules/ and dist/ are not included — npm install regenerates them.
