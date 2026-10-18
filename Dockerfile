# Multi-stage Dockerfile for unified Comment-Analyzer deployment
# Stage 1: Build Angular Frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build -- --configuration production

# Stage 2: Python Backend & Unified Static Serving
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download NLTK vader_lexicon
RUN python -m nltk.downloader vader_lexicon

# Copy backend application code
COPY backend ./backend
COPY *.py ./
COPY .env.example ./.env.example

# Copy compiled Angular frontend from Stage 1
COPY --from=frontend-builder /app/frontend/dist/frontend/browser ./frontend/dist/frontend/browser

# Ensure runtime directories exist
RUN mkdir -p /app/data

# Port configuration (dynamic PORT injection for Render / Railway / Heroku / Fly.io)
ENV PORT=8000
ENV PYTHONUNBUFFERED=1
ENV WEB_CONCURRENCY=1

EXPOSE 8000

# Start FastAPI server
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
