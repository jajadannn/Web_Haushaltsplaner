# syntax=docker/dockerfile:1
# Finanzplaner: Oberfläche und API in einem Image.
# Start über docker compose (siehe README, „Mit Docker betreiben“).

# --- 1. Oberfläche bauen ------------------------------------------------------------
FROM node:24-slim AS frontend
WORKDIR /src/frontend
# Playwright ist nur für die Browser-Durchklicks da – keine Browser herunterladen
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- 2. Laufzeit: Python, API, Worker ----------------------------------------------------
FROM python:3.14-slim AS app
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv

# Zeitzonendaten für zoneinfo (das Python-Paket tzdata gibt es nur unter Windows)
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    TZ=Europe/Berlin \
    IMPORT_DIR=/data/imports \
    DOCUMENT_DIR=/data/documents

WORKDIR /srv/finanzplaner

# Abhängigkeiten zuerst – dieser Schritt bleibt im Cache, solange uv.lock gleich bleibt
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY --from=frontend /src/frontend/dist ./frontend/dist
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

RUN useradd --system --uid 1000 --home-dir /srv/finanzplaner finanzplaner \
    && mkdir -p /data/imports /data/documents \
    && chown finanzplaner /data/imports /data/documents \
    && chmod 755 /usr/local/bin/entrypoint.sh
USER finanzplaner
VOLUME /data/imports /data/documents

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]

ENTRYPOINT ["entrypoint.sh"]
CMD ["serve"]
