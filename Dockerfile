# ============================================================
# Multi-stage Dockerfile for AI Code Review Assistant
# Unified Single Application (Frontend + Backend on 1 URL)
# ============================================================

# ---------- Stage 1: Build React Frontend ----------
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
ENV REACT_APP_API_BASE_URL=""
RUN npm run build

# ---------- Stage 2: Python FastAPI Backend + Static Server ----------
FROM python:3.11-slim AS runner
WORKDIR /app

# Install system dependencies if required
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r ./backend/requirements.txt

# Copy backend codebase
COPY backend/ ./backend/

# Copy built frontend assets into backend/static or frontend/build
COPY --from=frontend-builder /app/frontend/build ./frontend/build

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

EXPOSE 8000

WORKDIR /app/backend
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
