# mebot single image: FastAPI serves the API, the built app, the embed bundle and the
# widget loader. Build: docker build -t mebot .   Run: see docker-compose.yml

# --- 1: frontend (app + embed + loader) -------------------------------------------
FROM node:22-alpine AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- 2: runtime --------------------------------------------------------------------
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=UTC \
    DATA_DIR=/data \
    FRONTEND_DIST=/app/static

WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY backend/mebot ./mebot
COPY --from=frontend /src/dist /app/static
COPY deploy/docker/entrypoint.sh /usr/local/bin/mebot-entrypoint

RUN chmod 0755 /usr/local/bin/mebot-entrypoint \
    && useradd --system --uid 10001 --home-dir /app mebot \
    && mkdir -p /data && chown mebot /data

USER mebot
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).status == 200 else 1)"

ENTRYPOINT ["mebot-entrypoint"]
