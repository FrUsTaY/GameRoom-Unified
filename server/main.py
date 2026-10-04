"""
GAME-ROOM's Backlog Web Application - Main Server
FastAPI Server configured for local and network access (Port 8080 / Tailscale).
Implements unified authentication supporting:
1. Android Bearer Sync Token (preserving full APK v1.0.0 compatibility).
2. Web Server-Side Session Auth with HttpOnly, SameSite=Strict cookies.
"""
import os
import csv
import io
import json
import secrets
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Header, UploadFile, File, Response, Depends, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, HTMLResponse, RedirectResponse

import database as db
import rawg_service as rawg
import gigachat_service as ai
import yandex_disk_service as yandex
import youtube_service as yt
import sync_service
import security
from security import (
    verify_auth,
    verify_sync_token,
    get_or_create_sync_token,
    create_web_session,
    revoke_session,
    is_valid_web_session,
    has_web_credentials,
    get_web_credentials,
    login_limiter,
    verify_password,
    DUMMY_ARGON2_HASH,
    SESSION_COOKIE_NAME
)
from models import (
    GameCreate, GameUpdate, QuickTimeUpdate, 
    SettingsUpdate, ChatRequest, BackupRequest, RestoreRequest,
    QuickAddRawgRequest, MoveStatusRequest, ClearStatusRequest,
    SyncRequest, SyncResponse, InitialSyncRequest, InitialSyncResponse,
    LoginRequest
)

# Initialize database schema
db.init_db()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Verify environment configuration on startup
    if not has_web_credentials():
        print("\n" + "!" * 72)
        print("[CRITICAL WARNING] GameRoom Web credentials not configured!")
        print("Set GAME_ROOM_WEB_USERNAME and GAME_ROOM_WEB_PASSWORD_HASH in environment.")
        print("Web login endpoint will return a configuration error until set.")
        print("!" * 72 + "\n")
    yield

app = FastAPI(
    title="GAME-ROOM's Backlog Tracker",
    description="Cyber Comic Game Backlog Web App with StopGame SVG Ratings, RAWG, GigaChat AI and Yandex.Disk Cloud Sync",
    version="3.0.0",
    docs_url=None,      # Disabled on production for security
    redoc_url=None,     # Disabled on production for security
    openapi_url=None,   # Disabled on production for security
    lifespan=lifespan
)

# CORS configured securely: allows cross-origin requests from API/Android clients
# without exposing ambient browser cookie credentials to cross-origin attackers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Absolute Static files directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
static_dir = os.path.join(BASE_DIR, "static")
os.makedirs(static_dir, exist_ok=True)
os.makedirs(os.path.join(static_dir, "css"), exist_ok=True)
os.makedirs(os.path.join(static_dir, "js"), exist_ok=True)
os.makedirs(os.path.join(static_dir, "assets"), exist_ok=True)
os.makedirs(os.path.join(static_dir, "assets", "ratings"), exist_ok=True)


# ============================================================================
# Authentication API
# ============================================================================

@app.post("/api/auth/login")
def auth_login(req: LoginRequest, request: Request, response: Response):
    """
    Public login endpoint for Web client.
    Requires valid username and password matching configured Argon2id hash.
    Rate-limited to prevent brute-force attacks.
    On success: creates server-side session and sets HttpOnly, SameSite=Strict cookie.
    """
    # 1. Check if server credentials are configured in environment
    configured_user, configured_hash = get_web_credentials()
    if not configured_user or not configured_hash:
        raise HTTPException(
            status_code=500,
            detail="Ошибка конфигурации сервера: учётные данные веб-авторизации (GAME_ROOM_WEB_USERNAME / GAME_ROOM_WEB_PASSWORD_HASH) не настроены на сервере."
        )

    # 2. Check brute-force limiter
    login_limiter.check(request)

    # 3. Compare username in constant time
    username_match = secrets.compare_digest(req.username.strip(), configured_user.strip())

    if not username_match:
        # Dummy verification to prevent timing attacks leaking username existence
        verify_password(DUMMY_ARGON2_HASH, req.password)
        login_limiter.record_failure(request)
        raise HTTPException(status_code=401, detail="Неверное имя пользователя или пароль.")

    # 4. Verify password against Argon2id hash
    if not verify_password(configured_hash, req.password):
        login_limiter.record_failure(request)
        raise HTTPException(status_code=401, detail="Неверное имя пользователя или пароль.")

    # 5. Success: reset rate limit counter and issue session
    login_limiter.record_success(request)
    session_token = create_web_session(response, request)

    return {
        "success": True,
        "message": "Авторизация успешна.",
        "username": configured_user
    }

@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response, auth: dict = Depends(verify_auth)):
    """
    Revokes the current server session in SQLite and clears the session cookie.
    """
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if session_token:
        revoke_session(session_token, response)
    else:
        response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return {"success": True, "message": "Сессия успешно завершена."}

@app.get("/api/auth/me")
def auth_me(auth: dict = Depends(verify_auth)):
    """
    Returns current authentication status and user details.
    Accessible via both Web session and Android Bearer Sync Token.
    """
    return {
        "authenticated": True,
        "auth_type": auth.get("auth_type"),
        "user": auth.get("user") or auth.get("client") or "user"
    }


# ============================================================================
# Healthcheck (Public for Docker / Monitoring)
# ============================================================================

@app.get("/api/health")
def healthcheck():
    """Unauthenticated healthcheck for Docker and container monitoring."""
    return {"status": "ok"}


# ============================================================================
# Routes for Games (Protected)
# ============================================================================

@app.get("/api/games", dependencies=[Depends(verify_auth)])
def list_games(
    status: Optional[str] = Query(None, description="Filter by status ('playing', 'backlog', 'wishlist', 'completed', 'dropped', 'paused')"),
    platform: Optional[str] = Query(None, description="Filter by platform ('PC', 'PlayStation 5', 'Nintendo Switch', etc.)"),
    genre: Optional[str] = Query(None, description="Filter by genre"),
    rating_grade: Optional[str] = Query(None, description="Filter by rating grade ('izumitelno', 'pohvalno', 'prohodnyak', 'musor')"),
    search: Optional[str] = Query(None, description="Search term across title/notes"),
    sort_by: Optional[str] = Query("created_at_desc", description="Sorting option")
):
    games = db.get_games(status=status, platform=platform, genre=genre, rating_grade=rating_grade, search=search, sort_by=sort_by)
    return {"games": games, "total": len(games)}

@app.get("/api/games/{game_id}", dependencies=[Depends(verify_auth)])
def get_game(game_id: int):
    game = db.get_game_by_id(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Игра не найдена в базе данных.")
    return game

@app.post("/api/games", dependencies=[Depends(verify_auth)])
def add_game(game: GameCreate):
    created = db.create_game(game.dict())
    return {"success": True, "game": created}

@app.put("/api/games/{game_id}", dependencies=[Depends(verify_auth)])
@app.patch("/api/games/{game_id}", dependencies=[Depends(verify_auth)])
def edit_game(game_id: int, updates: GameUpdate):
    update_data = {k: v for k, v in updates.dict().items() if v is not None}
    updated = db.update_game(game_id, update_data)
    if not updated:
        raise HTTPException(status_code=404, detail="Игра не найдена.")
    return {"success": True, "game": updated}

@app.delete("/api/games/{game_id}", dependencies=[Depends(verify_auth)])
def remove_game(game_id: int):
    success = db.delete_game(game_id)
    if not success:
        raise HTTPException(status_code=404, detail="Игра не найдена.")
    return {"success": True, "deleted_id": game_id}

@app.post("/api/games/move-status", dependencies=[Depends(verify_auth)])
def move_status_endpoint(req: MoveStatusRequest):
    count = db.move_games_status(req.from_status, req.to_status)
    return {"success": True, "moved_count": count, "message": f"Перенесено игр: {count}"}

@app.post("/api/games/clear-status", dependencies=[Depends(verify_auth)])
def clear_status_endpoint(req: ClearStatusRequest):
    count = db.clear_games_status(req.status)
    return {"success": True, "deleted_count": count, "message": f"Удалено игр: {count}"}

@app.post("/api/games/{game_id}/quick-time", dependencies=[Depends(verify_auth)])
def add_quick_playtime(game_id: int, data: QuickTimeUpdate):
    updated = db.log_playtime(game_id, data.additional_minutes, data.note)
    if not updated:
        raise HTTPException(status_code=404, detail="Игра не найдена.")
    return {"success": True, "game": updated}

@app.get("/api/stats", dependencies=[Depends(verify_auth)])
def get_backlog_stats():
    return db.get_stats()


# ============================================================================
# RAWG.io Integration (Protected)
# ============================================================================

@app.get("/api/rawg/search", dependencies=[Depends(verify_auth)])
def search_rawg(query: str = Query(..., description="Query for RAWG game search")):
    return rawg.search_games(query)

@app.get("/api/rawg/game/{game_id_or_slug}", dependencies=[Depends(verify_auth)])
def get_rawg_details(game_id_or_slug: str):
    return rawg.get_game_details(game_id_or_slug)

@app.post("/api/rawg/quick-add", dependencies=[Depends(verify_auth)])
def quick_add_rawg(req: QuickAddRawgRequest):
    return rawg.quick_add_game(
        rawg_id=req.rawg_id, 
        target_status=req.target_status, 
        game_data=req.game_data
    )

@app.get("/api/rawg/missing-count", dependencies=[Depends(verify_auth)])
def rawg_missing_count(status: Optional[str] = Query(None)):
    games = db.get_games(status=status)
    missing = [g for g in games if not g.get("cover_url") or g.get("cover_url").strip() == ""]
    return {
        "missing_count": len(missing),
        "total_games": len(games)
    }

@app.post("/api/rawg/enrich-game/{game_id}", dependencies=[Depends(verify_auth)])
def rawg_enrich_game(game_id: int):
    return rawg.enrich_single_game(game_id)

@app.post("/api/rawg/bulk-enrich", dependencies=[Depends(verify_auth)])
def rawg_bulk_enrich(
    status: Optional[str] = Query(None),
    batch_size: Optional[int] = Query(25)
):
    return rawg.bulk_enrich_missing_games(status=status, batch_size=batch_size or 25)


# ============================================================================
# GigaChat AI Assistant Integration (Protected)
# ============================================================================

@app.post("/api/ai/chat", dependencies=[Depends(verify_auth)])
def chat_with_assistant(request: ChatRequest):
    history_dicts = [{"role": m.role, "content": m.content} for m in request.history]
    result = ai.generate_ai_response(
        user_message=request.message,
        history=history_dicts,
        include_context=request.include_backlog_context,
        action_type=request.action_type or "chat"
    )
    return result

@app.get("/api/ai/history", dependencies=[Depends(verify_auth)])
def get_chat_history():
    return {"history": db.get_ai_history()}

@app.delete("/api/ai/history", dependencies=[Depends(verify_auth)])
def clear_chat_history():
    db.clear_ai_history()
    return {"success": True, "message": "История чата очищена."}


# ============================================================================
# Yandex.Disk Cloud Backup (Protected)
# ============================================================================

@app.get("/api/yandex/status", dependencies=[Depends(verify_auth)])
def yandex_status():
    return yandex.check_yandex_status()

@app.post("/api/yandex/backup", dependencies=[Depends(verify_auth)])
def yandex_backup(req: BackupRequest = None):
    note = req.note if req else "Manual Backup"
    return yandex.create_cloud_backup(note=note)

@app.get("/api/yandex/backups", dependencies=[Depends(verify_auth)])
def yandex_list_backups():
    return yandex.list_cloud_backups()

@app.post("/api/yandex/delete", dependencies=[Depends(verify_auth)])
def yandex_delete(req: RestoreRequest):
    return yandex.delete_cloud_backup(req.backup_path)

@app.post("/api/yandex/restore", dependencies=[Depends(verify_auth)])
def yandex_restore(req: RestoreRequest):
    return yandex.restore_cloud_backup(req.backup_path)


# ============================================================================
# Full Bundle Export & Import (Protected)
# ============================================================================

@app.get("/api/export/full-bundle", dependencies=[Depends(verify_auth)])
def export_full_bundle():
    """
    Exports full backup bundle. Web authentication credentials and session records
    are strictly excluded to guarantee security.
    """
    data = db.export_full_database_json()
    filename = f"gameroom_full_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    json_str = json.dumps(data, ensure_ascii=False, indent=2)
    return Response(
        content=json_str,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.post("/api/import/full-bundle", dependencies=[Depends(verify_auth)])
async def import_full_bundle(file: UploadFile = File(...)):
    """
    Imports full backup bundle. Preserves web session state and prevents overriding
    web authentication credentials.
    """
    try:
        content = await file.read()
        data = json.loads(content.decode("utf-8"))
        result = db.import_full_database_json(data)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка импорта единого бандла: {str(e)}")

# Legacy export routes (Protected)
@app.get("/api/export/json", dependencies=[Depends(verify_auth)])
def export_json():
    return export_full_bundle()

@app.get("/api/export/csv", dependencies=[Depends(verify_auth)])
def export_csv():
    games = db.get_games()
    output = io.StringIO()
    writer = csv.writer(output)
    
    headers = [
        "ID", "Название", "Статус", "Платформа", "Жанры", "Дата выхода", 
        "Разработчик", "Рейтинг RAWG", "Оценка StopGame", "Время прохождения (часы)", 
        "Наиграно (часы)", "Приоритет", "Отзыв", "Заметки"
    ]
    writer.writerow(headers)
    
    for g in games:
        writer.writerow([
            g.get("id"),
            g.get("title"),
            g.get("status"),
            g.get("platform"),
            g.get("genres"),
            g.get("release_date"),
            g.get("developer"),
            g.get("rawg_rating"),
            g.get("rating_grade"),
            g.get("playtime_main"),
            round(g.get("user_playtime_minutes", 0) / 60.0, 1),
            g.get("priority"),
            g.get("user_review"),
            g.get("notes")
        ])
        
    output.seek(0)
    filename = f"gameroom_backlog_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        content=output.getvalue().encode('utf-8-sig'),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.post("/api/import/json", dependencies=[Depends(verify_auth)])
async def import_json(file: UploadFile = File(...)):
    return await import_full_bundle(file=file)


# ============================================================================
# YouTube Video & Trailer Integration (Protected)
# ============================================================================

@app.get("/api/youtube/trailer", dependencies=[Depends(verify_auth)])
def get_game_trailer(
    title: str = Query(..., description="Game title to find trailer for"),
    platform: Optional[str] = Query(None, description="Game platform"),
    mode: Optional[str] = Query("trailer", description="Mode: trailer, gameplay, launch, review")
):
    return yt.get_game_video(title=title, platform=platform, mode=mode)

@app.get("/api/youtube/search", dependencies=[Depends(verify_auth)])
def search_youtube_videos(
    query: str = Query(..., description="Custom YouTube search query"),
    max_results: Optional[int] = Query(4, description="Maximum video results to return")
):
    return yt.search_youtube(query=query, max_results=max_results)


# ============================================================================
# Distributed Sync API (Android APK v1.0.0 ↔ Web Server)
# ============================================================================

@app.post("/api/sync", response_model=SyncResponse, dependencies=[Depends(verify_auth)])
def sync_endpoint(req: SyncRequest):
    """
    Bidirectional delta-synchronization endpoint.
    Protected by verify_auth (accepts Android Bearer Sync Token or Web session).
    """
    return sync_service.process_sync(req)

@app.post("/api/sync/initial", response_model=InitialSyncResponse, dependencies=[Depends(verify_auth)])
def initial_sync_endpoint(req: InitialSyncRequest):
    """
    Initial sync endpoint for safely merging existing Android backlog with server backlog.
    Protected by verify_auth (accepts Android Bearer Sync Token or Web session).
    """
    return sync_service.process_initial_sync(req)

@app.get("/api/sync/status", dependencies=[Depends(verify_auth)])
def sync_status_endpoint():
    """
    Checks sync server health, total games count and current server time.
    Protected by verify_auth (accepts Android Bearer Sync Token or Web session).
    """
    games = db.get_games()
    return {
        "status": "online",
        "server_time": datetime.now(timezone.utc).isoformat(),
        "total_games": len(games),
        "sync_protocol_version": "1.0"
    }


# ============================================================================
# Settings (Protected & Sanitized)
# ============================================================================

SECRET_SETTINGS_KEYS = {
    "gameroom_sync_token",
    "rawg_api_key",
    "youtube_api_key",
    "gigachat_auth_key",
    "yandex_disk_token",
}

@app.get("/api/settings", dependencies=[Depends(verify_auth)])
def get_settings():
    """
    Returns application configuration.
    CRITICAL SECURITY: Never returns real secret keys or sync tokens to the frontend.
    Returns boolean flags indicating whether each service is configured.
    """
    all_settings = db.get_all_settings()
    sync_token = db.get_setting("gameroom_sync_token")
    
    # Filter out sensitive credentials from output
    safe_settings = {k: v for k, v in all_settings.items() if k not in SECRET_SETTINGS_KEYS}

    rawg_ok = bool(all_settings.get("rawg_api_key", "").strip())
    yt_ok = bool(all_settings.get("youtube_api_key", "").strip())
    giga_ok = bool(all_settings.get("gigachat_auth_key", "").strip())
    yd_ok = bool(all_settings.get("yandex_disk_token", "").strip())
    sync_ok = bool(sync_token and sync_token.strip())

    return {
        "settings": safe_settings,
        "rawg_configured": rawg_ok,
        "youtube_configured": yt_ok,
        "gigachat_configured": giga_ok,
        "yandex_configured": yd_ok,
        "sync_token_configured": sync_ok,
        # Backward compatibility aliases for frontend
        "is_rawg_configured": rawg_ok,
        "is_youtube_configured": yt_ok,
        "is_gigachat_configured": giga_ok,
        "is_yandex_configured": yd_ok
    }

@app.post("/api/settings", dependencies=[Depends(verify_auth)])
def update_settings(data: SettingsUpdate):
    """
    Updates settings safely.
    Empty/masked values for secret fields do NOT overwrite existing secrets.
    """
    db.save_safe_settings_dict(data.settings)
    return {"success": True, "message": "Настройки сохранены."}


# ============================================================================
# Web UI & Static Files
# ============================================================================

app.mount("/css", StaticFiles(directory=os.path.join(static_dir, "css")), name="css")
app.mount("/js", StaticFiles(directory=os.path.join(static_dir, "js")), name="js")
app.mount("/assets", StaticFiles(directory=os.path.join(static_dir, "assets")), name="assets")

@app.get("/")
@app.get("/index.html")
def serve_index(request: Request):
    """
    Serves main GameRoom application to authenticated users.
    Unauthenticated users are served the login page.
    """
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if session_token and is_valid_web_session(session_token):
        index_file = os.path.join(static_dir, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file, media_type="text/html", headers={"Cache-Control": "no-store"})

    login_file = os.path.join(static_dir, "login.html")
    if os.path.exists(login_file):
        return FileResponse(login_file, media_type="text/html", headers={"Cache-Control": "no-store"})
    return HTMLResponse("<h1>GAME-ROOM's Backlog Tracker</h1><p>login.html not found</p>", status_code=404)

@app.get("/login")
def serve_login(request: Request):
    """
    Serves login page. If already authenticated, redirects to main backlog.
    """
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if session_token and is_valid_web_session(session_token):
        return RedirectResponse(url="/", status_code=303)

    login_file = os.path.join(static_dir, "login.html")
    if os.path.exists(login_file):
        return FileResponse(login_file, media_type="text/html", headers={"Cache-Control": "no-store"})
    return HTMLResponse("<h1>GAME-ROOM's Backlog Tracker</h1><p>login.html not found</p>", status_code=404)

@app.get("/manifest.json")
def serve_manifest():
    p = os.path.join(static_dir, "manifest.json")
    if os.path.exists(p):
        return FileResponse(p, media_type="application/manifest+json")
    raise HTTPException(status_code=404, detail="manifest.json not found")

@app.get("/sw.js")
def serve_sw():
    p = os.path.join(static_dir, "sw.js")
    if os.path.exists(p):
        return FileResponse(p, media_type="application/javascript")
    raise HTTPException(status_code=404, detail="sw.js not found")

@app.get("/favicon.ico")
def serve_favicon_ico():
    p = os.path.join(static_dir, "favicon.ico")
    if os.path.exists(p):
        return FileResponse(p, media_type="image/x-icon")
    raise HTTPException(status_code=404, detail="favicon.ico not found")

@app.get("/favicon.png")
def serve_favicon_png():
    p = os.path.join(static_dir, "favicon.png")
    if os.path.exists(p):
        return FileResponse(p, media_type="image/png")
    raise HTTPException(status_code=404, detail="favicon.png not found")

@app.get("/{full_path:path}")
def serve_static_or_spa(full_path: str, request: Request):
    file_path = os.path.join(static_dir, full_path)
    if os.path.isfile(file_path):
        if full_path in ("index.html",):
            return serve_index(request)
        return FileResponse(file_path)
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API endpoint not found")
    return serve_index(request)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
