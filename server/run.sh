#!/usr/bin/env bash
echo "================================================================"
echo "  SPIDER-VERSE // MULTIVERSE GAME BACKLOG TRACKER"
echo "  Host: 0.0.0.0  |  Port: 8080"
echo "  Tailscale & Mobile Access Enabled"
echo "================================================================"
echo ""
echo "Проверка зависимостей..."
python3 -m pip install -r requirements.txt --quiet
echo ""
echo "[OK] Сервер запускается на порту 8080!"
echo ""
echo "  * Локальный доступ на ПК:        http://localhost:8080"
echo "  * Доступ в локальной сети (LAN): http://[IP-компьютера]:8080"
echo "  * Доступ со смартфона (Tailscale): http://[Tailscale-IP]:8080"
echo ""
echo "Нажмите Ctrl+C для остановки сервера."
echo "================================================================"
python3 -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload
