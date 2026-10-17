# Advanced: nginx + backend (two containers)

The pre-0.9 layout: nginx serves the built UI and proxies `/api`, `/embed/` and the
widget loader to the backend container. Use it only if you already run nginx-style
static hosting and want it in its own container. **The single image in the repo root
(`docker-compose.yml`) does all of this in one process and is the supported default.**

```bash
cd deploy/nginx
docker compose up -d --build   # http://localhost:8080
```

Data lives in `deploy/nginx/data/` (mounted at `/data` in the backend container).
The data directory layout is identical to the single image's `/data`, so you can move
between the two by moving that directory (see `docs/upgrading.md`).
