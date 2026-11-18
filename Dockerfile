# ---- build the web UI ----
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- runtime: FastAPI + ffmpeg ----
FROM python:3.13-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY --from=web /web/dist frontend/dist

ENV CLIPWIZARD_DATA_DIR=/data \
    HF_HOME=/data/models \
    PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8000
WORKDIR /app/backend
# One process: background jobs run in-process (see app/jobs.py).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
