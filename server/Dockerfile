# Multi-stage / lightweight production Dockerfile for Game-Room-Web
FROM python:3.11-slim

# Labels
LABEL maintainer="Game-Room Project"
LABEL description="Game-Room FastAPI Backlog & Distributed Sync Server"

# Environment configuration
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080 \
    BACKLOG_DB_PATH=/app/data/backlog.db

# Install curl for Docker healthcheck and ca-certificates
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create non-root application user and group
RUN groupadd -g 1000 gameroom && \
    useradd -u 1000 -g gameroom -s /bin/bash -m gameroom

# Working directory
WORKDIR /app

# Install Python dependencies first for optimal Docker caching
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY --chown=gameroom:gameroom . .

# Create data directory for persistent SQLite database and set ownership
RUN mkdir -p /app/data && chown -R gameroom:gameroom /app

# Switch to non-root user
USER gameroom

# Expose HTTP port
EXPOSE 8080

# Healthcheck targeting sync status endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/api/health || exit 1

# Start Uvicorn ASGI server
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
