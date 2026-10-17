FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    REGISTRY_DATA_DIR=/app/data \
    REGISTRY_RELEASES=/app/releases.json

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY releases.json PRIVACY.md ./

# Run as an unprivileged user; /app/data is the only writable path.
RUN useradd --system --uid 10001 registry && mkdir -p /app/data && chown registry /app/data
USER registry

EXPOSE 8100
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8100/healthz', timeout=2).status == 200 else 1)"

# One process: the outbox/summary worker and rate-limit state live in memory.
# --no-access-log: the access log would write every client IP, which the registry promises not to keep.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100", "--no-access-log"]
