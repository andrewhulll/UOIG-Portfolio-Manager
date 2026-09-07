# UOIG Investment Terminal — single-container image.
# Builds the React frontend, then runs the FastAPI backend which serves both the
# API and the built frontend on one port.

# ---- Stage 1: build the React frontend ----
FROM node:20-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# ---- Stage 2: Python backend that also serves the built frontend ----
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY api/ ./api/
COPY src/ ./src/
COPY config.yaml ./
# Curated markdown the backend reads at runtime from the repo root:
# predictions.py -> PREDICTION_MARKETS.md (Predictions tab), thesis.py -> THESIS.md (Thesis tab).
# Without these the maps parse empty and both tabs render their "nothing mapped" stub.
COPY PREDICTION_MARKETS.md THESIS.md ./
COPY --from=web /web/dist ./web/dist
# No SQLite DB baked in — production reads Postgres via DATABASE_URL (Supabase).
# Bind the platform-provided $PORT (Render/Fly inject it); default 8000 locally.
ENV WEB_CONCURRENCY=1
EXPOSE 8000
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
