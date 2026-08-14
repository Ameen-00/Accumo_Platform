FROM python:3.12-slim

RUN useradd --create-home --uid 10001 accumo \
 && apt-get update \
 && apt-get install -y --no-install-recommends libpq5 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY packages ./packages
COPY apps ./apps

RUN mkdir -p /data/uploads /data/reports && chown -R accumo:accumo /data
USER accumo
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/packages/foundation:/app/packages/canonical:/app/packages/ingest:/app/packages/rules:/app/apps/pulse:/app/apps/api
WORKDIR /app/apps/api
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
