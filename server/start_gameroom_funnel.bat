@echo off
title GAME-ROOM's Backlog Server + Tailscale Funnel (Port 8080 / 8443)
color 0b

echo ================================================================
echo   GAME-ROOM's // MULTIVERSE BACKLOG TRACKER
echo   Local Port: 8080  ^|  Tailscale Funnel HTTPS Port: 8443
echo ================================================================
echo.

echo [1/3] Checking Python dependencies...
python -m pip install -r requirements.txt --quiet

echo.
echo [2/3] Configuring Public Tailscale Funnel on port 8443...
tailscale funnel --https=8443 --bg 8080

echo.
echo [3/3] Tailscale Status:
tailscale serve status
echo.
echo ================================================================
echo   ACCESS URLS:
echo   - Local PC:             http://localhost:8080
echo   - Mobile / Any Browser: https://user.tailabe7ee.ts.net:8443/
echo ================================================================
echo.
echo Starting Web Server on 0.0.0.0:8080...
echo Press Ctrl+C to stop the server.
echo.

python -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload

pause
