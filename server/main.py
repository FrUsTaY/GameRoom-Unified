"""
GAME-ROOM's Backlog Web Application - Main Server
FastAPI Server configured for local and network access (Port 8080 / Tailscale)
"""
import os
import csv
import io
import json
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Query, Header, UploadFile, File, Response, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

import database as db
import rawg_service as rawg
import gigachat_service as ai
import yandex_disk_service as yandex
import youtube_service as yt
import sync_service
import security
from security import verify_sync_token, get_or_create_sync_token
from models import (
    GameCreate, GameUpdate, QuickTimeUpdate, 
    SettingsUpdate, ChatRequest, BackupRequest, RestoreRequest,
    QuickAddRawgRequest, MoveStatusRequest, ClearStatusRequest,
    SyncRequest, SyncResponse, InitialSyncRequest, InitialSyncResponse
)

# Initialize database
db.init_db()

app = FastAPI(
    title="GAME-ROOM's Backlog Tracker",
    description="Cyber Comic Game Backlog Web App with StopGame SVG Ratings, RAWG, GigaChat AI and Yandex.Disk Cloud Sync",
    version="3.0.0"
)

# Enable CORS for cross-device access (Tailscale / LAN)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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

# --- Routes for Games ---

@app.get("/api/games")
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

@app.get("/api/games/{game_id}")
def get_game(game_id: int):
    game = db.get_game_by_id(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Игра не найдена в базе данных.")
    return game

@app.post("/api/games")
def add_game(game: GameCreate):
    created = db.create_game(game.dict())
    return {"success": True, "game": created}

@app.put("/api/games/{game_id}")
@app.patch("/api/games/{game_id}")
def edit_game(game_id: int, updates: GameUpdate):
    update_data = {k: v for k, v in updates.dict().items() if v is not None}
    updated = db.update_game(game_id, update_data)
    if not updated:
        raise HTTPException(status_code=404, detail="Игра не найдена.")
    return {"success": True, "game": updated}

@app.delete("/api/games/{game_id}")
def remove_game(game_id: int):
    success = db.delete_game(game_id)
    if not success:
        raise HTTPException(status_code=404, detail="Игра не найдена.")
    return {"success": True, "deleted_id": game_id}


@app.post("/api/games/move-status")
def move_status_endpoint(req: MoveStatusRequest):
    count = db.move_games_status(req.from_status, req.to_status)
    return {"success": True, "moved_count": count, "message": f"Перенесено игр: {count}"}

@app.post("/api/games/clear-status")
def clear_status_endpoint(req: ClearStatusRequest):
    count = db.clear_games_status(req.status)
    return {"success": True, "deleted_count": count, "message": f"Удалено игр: {count}"}

@app.post("/api/games/{game_id}/quick-time")
def add_quick_playtime(game_id: int, data: QuickTimeUpdate):
    updated = db.log_playtime(game_id, data.additional_minutes, data.note)
    if not updated:
        raise HTTPException(status_code=404, detail="Игра не найдена.")
    return {"success": True, "game": updated}

@app.get("/api/stats")
def get_backlog_stats():
    return db.get_stats()

# --- RAWG.io Integration ---

@app.get("/api/rawg/search")
def search_rawg(query: str = Query(..., description="Query for RAWG game search")):
    return rawg.search_games(query)

@app.get("/api/rawg/game/{game_id_or_slug}")
def get_rawg_details(game_id_or_slug: str):
    return rawg.get_game_details(game_id_or_slug)

@app.post("/api/rawg/quick-add")
def quick_add_rawg(req: QuickAddRawgRequest):
    return rawg.quick_add_game(
        rawg_id=req.rawg_id, 
        target_status=req.target_status, 
        game_data=req.game_data
    )


@app.get("/api/rawg/missing-count")
def rawg_missing_count(status: Optional[str] = Query(None)):
    games = db.get_games(status=status)
    missing = [g for g in games if not g.get("cover_url") or g.get("cover_url").strip() == ""]
    return {
        "missing_count": len(missing),
        "total_games": len(games)
    }

@app.post("/api/rawg/enrich-game/{game_id}")
def rawg_enrich_game(game_id: int):
    return rawg.enrich_single_game(game_id)

@app.post("/api/rawg/bulk-enrich")
def rawg_bulk_enrich(
    status: Optional[str] = Query(None),
    batch_size: Optional[int] = Query(25)
):
    return rawg.bulk_enrich_missing_games(status=status, batch_size=batch_size or 25)

# --- GigaChat AI Assistant Integration ---

@app.post("/api/ai/chat")
def chat_with_assistant(request: ChatRequest):
    history_dicts = [{"role": m.role, "content": m.content} for m in request.history]
    result = ai.generate_ai_response(
        user_message=request.message,
        history=history_dicts,
        include_context=request.include_backlog_context,
        action_type=request.action_type or "chat"
    )
    return result

@app.get("/api/ai/history")
def get_chat_history():
    return {"history": db.get_ai_history()}

@app.delete("/api/ai/history")
def clear_chat_history():
    db.clear_ai_history()
    return {"success": True, "message": "История чата очищена."}

# --- Yandex.Disk & Backup Integration ---

@app.get("/api/yandex/status")
def yandex_status():
    return yandex.check_yandex_status()

@app.post("/api/yandex/backup")
def yandex_backup(req: BackupRequest = None):
    note = req.note if req else "Manual Backup"
    return yandex.create_cloud_backup(note=note)

@app.get("/api/yandex/backups")
def yandex_list_backups():
    return yandex.list_cloud_backups()

@app.post("/api/yandex/delete")
def yandex_delete(req: RestoreRequest):
    return yandex.delete_cloud_backup(req.backup_path)

@app.post("/api/yandex/restore")
def yandex_restore(req: RestoreRequest):
    return yandex.restore_cloud_backup(req.backup_path)

# --- Single-File Full Bundle Export & Import ---

@app.get("/api/export/full-bundle")
def export_full_bundle():
    data = db.export_full_database_json()
    filename = f"gameroom_full_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    json_str = json.dumps(data, ensure_ascii=False, indent=2)
    return Response(
        content=json_str,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.post("/api/import/full-bundle")
async def import_full_bundle(file: UploadFile = File(...)):
    try:
        content = await file.read()
        data = json.loads(content.decode("utf-8"))
        result = db.import_full_database_json(data)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ошибка импорта единого бандла: {str(e)}")

# Legacy export routes
@app.get("/api/export/json")
def export_json():
    return export_full_bundle()

@app.get("/api/export/csv")
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

@app.post("/api/import/json")
async def import_json(file: UploadFile = File(...)):
    return await import_full_bundle(file=file)


# --- YouTube Video & Trailer Integration ---

@app.get("/api/youtube/trailer")
def get_game_trailer(
    title: str = Query(..., description="Game title to find trailer for"),
    platform: Optional[str] = Query(None, description="Game platform"),
    mode: Optional[str] = Query("trailer", description="Mode: trailer, gameplay, launch, review")
):
    return yt.get_game_video(title=title, platform=platform, mode=mode)

@app.get("/api/youtube/search")
def search_youtube_videos(
    query: str = Query(..., description="Custom YouTube search query"),
    max_results: Optional[int] = Query(4, description="Maximum video results to return")
):
    return yt.search_youtube(query=query, max_results=max_results)

# --- Distributed Sync API (Android ↔ Web) ---

@app.post("/api/sync", response_model=SyncResponse)
def sync_endpoint(req: SyncRequest, authenticated: bool = Depends(verify_sync_token)):
    """
    Bidirectional delta-synchronization endpoint.
    Applies incoming created/updated/deleted changes with LWW conflict resolution
    and returns all server-side updates and tombstones since last_sync_timestamp.
    """
    return sync_service.process_sync(req)

@app.post("/api/sync/initial", response_model=InitialSyncResponse)
def initial_sync_endpoint(req: InitialSyncRequest, authenticated: bool = Depends(verify_sync_token)):
    """
    Initial sync endpoint for safely merging existing Android backlog with server backlog
    using 3-level strict deduplication (RAWG ID -> Title+Platform+Year -> Separate record).
    """
    return sync_service.process_initial_sync(req)

@app.get("/api/health")
def healthcheck():
    """Unauthenticated healthcheck for Docker and container monitoring."""
    return {"status": "ok"}

@app.get("/api/sync/status")
def sync_status_endpoint(authenticated: bool = Depends(verify_sync_token)):
    """
    Checks sync server health, total games count and current server time.
    Requires valid sync token.
    """
    from datetime import timezone
    games = db.get_games()
    return {
        "status": "online",
        "server_time": datetime.now(timezone.utc).isoformat(),
        "total_games": len(games),
        "sync_protocol_version": "1.0"
    }

# --- Settings ---

@app.get("/api/settings")
def get_settings():
    settings = db.get_all_settings()
    sync_token = db.get_setting("gameroom_sync_token")
    return {
        "settings": settings,
        "is_rawg_configured": bool(settings.get("rawg_api_key", "").strip()),
        "is_youtube_configured": bool(settings.get("youtube_api_key", "").strip()),
        "is_gigachat_configured": bool(settings.get("gigachat_auth_key", "").strip()),
        "is_yandex_configured": bool(settings.get("yandex_disk_token", "").strip()),
        "gameroom_sync_token": sync_token
    }

@app.post("/api/settings")
def update_settings(data: SettingsUpdate):
    db.save_settings_dict(data.settings)
    return {"success": True, "message": "Настройки сохранены."}

# --- Explicit Static Mounting & SPA Fallback ---

# Mount asset subdirectories
app.mount("/css", StaticFiles(directory=os.path.join(static_dir, "css")), name="css")
app.mount("/js", StaticFiles(directory=os.path.join(static_dir, "js")), name="js")
app.mount("/assets", StaticFiles(directory=os.path.join(static_dir, "assets")), name="assets")

@app.get("/")
@app.get("/index.html")
def serve_index():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file, media_type="text/html")
    return HTMLResponse("<h1>GAME-ROOM's Backlog Tracker</h1><p>index.html not found</p>", status_code=404)

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

@app.get("/{full_path:path}")
def serve_static_or_spa(full_path: str):
    # Check if exact file exists in static_dir
    file_path = os.path.join(static_dir, full_path)
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    # If API path was requested and not found by router, return JSON 404
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API endpoint not found")
    # For any browser navigation route, return index.html
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file, media_type="text/html")
    return HTMLResponse("<h1>GAME-ROOM's Backlog Tracker</h1>", status_code=200)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
