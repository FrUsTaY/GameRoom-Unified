#!/usr/bin/env bash
# Game-Room Unified - Ubuntu Server 24.04 Deployment Helper
set -e

echo "====================================================="
echo "   Game-Room-Web Deployment Script for Ubuntu 24.04  "
echo "====================================================="

# Ensure data directory exists with correct permissions
mkdir -p ./data
# Set permissions for UID 1000 (gameroom inside container)
chmod 775 ./data
if id -u gameroom >/dev/null 2>&1; then
    chown -R gameroom:gameroom ./data
fi

# Copy existing database if it exists in current dir and not in ./data
if [ -f "backlog.db" ] && [ ! -f "./data/backlog.db" ]; then
    echo "📦 Copying existing backlog.db into ./data/backlog.db..."
    cp backlog.db ./data/backlog.db
    chmod 664 ./data/backlog.db
fi

# Create .env from .env.example if missing
if [ ! -f ".env" ]; then
    echo "⚙️ Creating .env from .env.example..."
    cp .env.example .env
fi

# Check Docker and Compose availability
if command -v docker >/dev/null 2>&1; then
    echo "🐳 Building and starting Docker container..."
    if docker compose version >/dev/null 2>&1; then
        docker compose up -d --build
    elif command -v docker-compose >/dev/null 2>&1; then
        docker-compose up -d --build
    else
        echo "❌ docker compose not found. Please install Docker Compose plugin."
        exit 1
    fi
    echo ""
    echo "✅ Game-Room-Web is running!"
    echo "📊 Health status: curl http://localhost:8080/api/sync/status"
else
    echo "❌ Docker is not installed. Please install Docker engine first."
    exit 1
fi
