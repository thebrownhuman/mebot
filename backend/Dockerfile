FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY migrations ./migrations
COPY mebot ./mebot

# data/ holds the sqlite db + generated secret.key; mounted as a volume in compose
RUN mkdir -p data
ENV TZ=UTC

EXPOSE 8000
CMD ["uvicorn", "mebot.main:app", "--host", "0.0.0.0", "--port", "8000"]
