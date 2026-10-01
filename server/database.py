"""
Database layer for GAME-ROOM's Backlog Application
Uses SQLite with automatic schema migration, full bundle backup/restore,
SVG rating grades ('izumitelno', 'pohvalno', 'prohodnyak', 'musor'), Russian genres, and AI history tracking.
"""
import sqlite3
import json
import os
import uuid
import secrets
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

def get_db_path() -> str:
    env_path = os.environ.get("BACKLOG_DB_PATH")
    if env_path:
        parent = os.path.dirname(os.path.abspath(env_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        return env_path
    
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    except Exception:
        base_dir = os.getcwd()
        
    local_path = os.path.join(base_dir, "backlog.db")
    return local_path

DB_PATH = get_db_path()

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Games table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS games (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        slug TEXT,
        rawg_id INTEGER,
        cover_url TEXT,
        background_url TEXT,
        status TEXT NOT NULL DEFAULT 'backlog', -- 'playing', 'backlog', 'wishlist', 'completed', 'dropped', 'paused'
        platform TEXT DEFAULT 'PC',
        platforms_list TEXT DEFAULT '[]',
        genres TEXT DEFAULT '',
        release_date TEXT DEFAULT '',
        developer TEXT DEFAULT '',
        publisher TEXT DEFAULT '',
        rawg_rating REAL DEFAULT 0.0,
        metacritic INTEGER DEFAULT 0,
        playtime_main REAL DEFAULT 0.0,
        playtime_extra REAL DEFAULT 0.0,
        playtime_completionist REAL DEFAULT 0.0,
        user_playtime_minutes INTEGER DEFAULT 0,
        rating_grade TEXT DEFAULT '', -- 'izumitelno', 'pohvalno', 'prohodnyak', 'musor', or ''
        user_score INTEGER DEFAULT 0,
        user_review TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        is_favorite INTEGER DEFAULT 0,
        priority TEXT DEFAULT 'medium', -- 'low', 'medium', 'high', 'urgent'
        created_at TEXT DEFAULT '',
        started_at TEXT DEFAULT '',
        completed_at TEXT DEFAULT '',
        last_played_at TEXT DEFAULT ''
    )
    ''')

    # Ensure rating_grade and sync columns exist if migrating from older schema
    cursor.execute("PRAGMA table_info(games)")
    columns = [col[1] for col in cursor.fetchall()]
    if "rating_grade" not in columns:
        try:
            cursor.execute("ALTER TABLE games ADD COLUMN rating_grade TEXT DEFAULT ''")
        except Exception:
            pass
    if "uuid" not in columns:
        try:
            cursor.execute("ALTER TABLE games ADD COLUMN uuid TEXT DEFAULT ''")
        except Exception:
            pass
    if "updated_at" not in columns:
        try:
            cursor.execute("ALTER TABLE games ADD COLUMN updated_at TEXT DEFAULT ''")
        except Exception:
            pass
    if "updated_by" not in columns:
        try:
            cursor.execute("ALTER TABLE games ADD COLUMN updated_by TEXT DEFAULT 'web-admin'")
        except Exception:
            pass
    if "client_created_at" not in columns:
        try:
            cursor.execute("ALTER TABLE games ADD COLUMN client_created_at TEXT DEFAULT ''")
        except Exception:
            pass

    # Ensure index on uuid and updated_at
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_games_uuid ON games(uuid) WHERE uuid IS NOT NULL AND uuid != ''")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_updated_at ON games(updated_at)")

    # Play sessions table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS play_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER NOT NULL,
        duration_minutes INTEGER NOT NULL,
        note TEXT DEFAULT '',
        created_at TEXT NOT NULL,
        FOREIGN KEY (game_id) REFERENCES games (id) ON DELETE CASCADE
    )
    ''')

    # Settings table (stores API keys, tokens, configuration)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    ''')

    # AI Chat History table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ai_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT NOT NULL, -- 'user', 'assistant'
        content TEXT NOT NULL,
        action_type TEXT DEFAULT 'chat',
        created_at TEXT NOT NULL
    )
    ''')

    # Sync Tombstones table (tracks deletions for distributed delta-sync)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sync_tombstones (
        uuid TEXT PRIMARY KEY,
        deleted_at TEXT NOT NULL,
        deleted_by TEXT NOT NULL,
        entity_type TEXT DEFAULT 'game',
        title_backup TEXT DEFAULT ''
    )
    ''')
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tombstones_deleted_at ON sync_tombstones(deleted_at)")

    default_settings = {
        "rawg_api_key": "",
        "youtube_api_key": "",
        "gigachat_auth_key": "",
        "gigachat_scope": "GIGACHAT_API_PERS",
        "yandex_disk_token": "",
        "yandex_backup_folder": "disk:/GameBacklog_Backups",
        "user_name": "Aleksey",
        "app_theme": "spider-verse",
        "gameroom_sync_token": ""
    }

    for k, v in default_settings.items():
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

    # Generate permanent sync token if not present
    cursor.execute("SELECT value FROM settings WHERE key = 'gameroom_sync_token'")
    token_row = cursor.fetchone()
    if not token_row or not token_row[0].strip():
        new_token = secrets.token_urlsafe(32)
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('gameroom_sync_token', ?)", (new_token,))

    # Auto-generate UUID and updated_at for existing games missing them
    cursor.execute("SELECT id FROM games WHERE uuid IS NULL OR uuid = ''")
    missing_uuids = cursor.fetchall()
    now_utc_str = datetime.now(timezone.utc).isoformat()
    for row in missing_uuids:
        cursor.execute(
            "UPDATE games SET uuid = ?, updated_at = COALESCE(NULLIF(updated_at, ''), ?), updated_by = 'migration' WHERE id = ?",
            (str(uuid.uuid4()), now_utc_str, row[0])
        )

    conn.commit()
    conn.close()
    
    seed_initial_data_if_empty()

def seed_initial_data_if_empty():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM games")
    count = cursor.fetchone()[0]
    
    if count == 0:
        now_str = datetime.now().isoformat()
        sample_games = [
            {
                "title": "The Last of Us Part II Remastered",
                "slug": "the-last-of-us-part-ii-remastered",
                "rawg_id": 974712,
                "cover_url": "https://media.rawg.io/media/games/043/043c7b2829286d9a5b3f11ab7284f67c.jpg",
                "background_url": "https://media.rawg.io/media/screenshots/6bf/6bfdc1b67e3a985f4eefee5f2fcb6c08.jpg",
                "status": "playing",
                "platform": "PC",
                "platforms_list": json.dumps(["PC", "PlayStation 5"]),
                "genres": "Экшен, Приключения, Сюжетная",
                "release_date": "2024-01-19",
                "developer": "Naughty Dog",
                "publisher": "PlayStation Publishing LLC",
                "rawg_rating": 4.5,
                "metacritic": 90,
                "playtime_main": 24.0,
                "playtime_extra": 31.0,
                "playtime_completionist": 42.0,
                "user_playtime_minutes": 780, # 13 hours
                "rating_grade": "",
                "user_score": 0,
                "user_review": "",
                "notes": "Потрясающая кинематографичность, плотный ганплей и стелс на максимальной сложности.",
                "is_favorite": 1,
                "priority": "high",
                "created_at": now_str,
                "started_at": "2026-08-15T12:00:00",
                "completed_at": "",
                "last_played_at": now_str
            },
            {
                "title": "Senua's Saga: Hellblade II",
                "slug": "senuas-saga-hellblade-ii",
                "rawg_id": 401664,
                "cover_url": "https://media.rawg.io/media/games/606/606990ae0ea5ee5d9d71c77f0a8276f5.jpg",
                "background_url": "https://media.rawg.io/media/screenshots/003/0037a54911cb3a890471bdf483b8a1c9.jpg",
                "status": "playing",
                "platform": "PC",
                "platforms_list": json.dumps(["PC", "Xbox Series S/X"]),
                "genres": "Экшен, Приключения, Психологический хоррор",
                "release_date": "2024-05-21",
                "developer": "Ninja Theory",
                "publisher": "Xbox Game Studios",
                "rawg_rating": 4.2,
                "metacritic": 81,
                "playtime_main": 7.5,
                "playtime_extra": 9.0,
                "playtime_completionist": 11.0,
                "user_playtime_minutes": 270, # 4.5 hours
                "rating_grade": "",
                "user_score": 0,
                "user_review": "",
                "notes": "Играть исключительно в хороших наушниках с бинауральным 3D звуком. Графика на Unreal Engine 5 невероятная.",
                "is_favorite": 1,
                "priority": "high",
                "created_at": now_str,
                "started_at": "2026-08-20T19:00:00",
                "completed_at": "",
                "last_played_at": now_str
            },
            {
                "title": "Ghost of Tsushima DIRECTOR'S CUT",
                "slug": "ghost-of-tsushima-directors-cut",
                "rawg_id": 612803,
                "cover_url": "https://media.rawg.io/media/games/505/5050f244192b0c3674d8124fa48db069.jpg",
                "background_url": "https://media.rawg.io/media/screenshots/5c7/5c7a52fce63b7ce2bca6ca50444dbef6.jpg",
                "status": "backlog",
                "platform": "PC",
                "platforms_list": json.dumps(["PC", "PlayStation 5"]),
                "genres": "Экшен, Приключения, Открытый мир",
                "release_date": "2024-05-16",
                "developer": "Sucker Punch Productions, Nixxes Software",
                "publisher": "PlayStation Publishing LLC",
                "rawg_rating": 4.6,
                "metacritic": 88,
                "playtime_main": 25.0,
                "playtime_extra": 44.0,
                "playtime_completionist": 62.0,
                "user_playtime_minutes": 0,
                "rating_grade": "",
                "user_score": 0,
                "user_review": "",
                "notes": "Пройти на геймпаде с полным погружением в режим самурая Куросавы.",
                "is_favorite": 1,
                "priority": "high",
                "created_at": now_str,
                "started_at": "",
                "completed_at": "",
                "last_played_at": ""
            },
            {
                "title": "Silent Hill 2 Remake",
                "slug": "silent-hill-2-remake",
                "rawg_id": 870420,
                "cover_url": "https://media.rawg.io/media/games/0df/0df1c998f4bbd0f8a8bb61501c64ebff.jpg",
                "background_url": "https://media.rawg.io/media/screenshots/316/3167b57b9c9fec719e71ec93e7f6dc74.jpg",
                "status": "backlog",
                "platform": "PC",
                "platforms_list": json.dumps(["PC", "PlayStation 5"]),
                "genres": "Хоррор, Выживание, Детектив",
                "release_date": "2024-10-08",
                "developer": "Bloober Team",
                "publisher": "Konami",
                "rawg_rating": 4.4,
                "metacritic": 86,
                "playtime_main": 15.0,
                "playtime_extra": 18.0,
                "playtime_completionist": 22.0,
                "user_playtime_minutes": 0,
                "rating_grade": "",
                "user_score": 0,
                "user_review": "",
                "notes": "Погружение в туманный Сайлент Хилл. Отличный психологический хоррор.",
                "is_favorite": 0,
                "priority": "medium",
                "created_at": now_str,
                "started_at": "",
                "completed_at": "",
                "last_played_at": ""
            },
            {
                "title": "Death Stranding 2: On the Beach",
                "slug": "death-stranding-2-on-the-beach",
                "rawg_id": 892556,
                "cover_url": "https://media.rawg.io/media/games/8ef/8ef309ee2e74da00f7e44b8ee78e8749.jpg",
                "background_url": "https://media.rawg.io/media/screenshots/c58/c589d98342898dbfce551ad36e846067.jpg",
                "status": "wishlist",
                "platform": "PC",
                "platforms_list": json.dumps(["PC", "PlayStation 5"]),
                "genres": "Sci-Fi, Приключения, Открытый мир",
                "release_date": "2025-11-01",
                "developer": "Kojima Productions",
                "publisher": "Sony Interactive Entertainment",
                "rawg_rating": 4.8,
                "metacritic": 0,
                "playtime_main": 35.0,
                "playtime_extra": 55.0,
                "playtime_completionist": 85.0,
                "user_playtime_minutes": 0,
                "rating_grade": "",
                "user_score": 0,
                "user_review": "",
                "notes": "Новый шедевр от Хидео Кодзимы с Норманом Ридусом и Леа Сейду. Ждать релиза на ПК!",
                "is_favorite": 1,
                "priority": "urgent",
                "created_at": now_str,
                "started_at": "",
                "completed_at": "",
                "last_played_at": ""
            },
            {
                "title": "Planet of Lana 2",
                "slug": "planet-of-lana-2",
                "rawg_id": 999901,
                "cover_url": "https://media.rawg.io/media/games/3b9/3b9df7ef354508ecbbef22301c34dd0f.jpg",
                "background_url": "https://media.rawg.io/media/screenshots/1bb/1bb6353d9e0ff5021e1a5f4c20aa11bc.jpg",
                "status": "completed",
                "platform": "PC",
                "platforms_list": json.dumps(["PC", "Nintendo Switch"]),
                "genres": "Платформер, Головоломка, Sci-Fi",
                "release_date": "2026-02-14",
                "developer": "Wishfully",
                "publisher": "Thunderful Publishing",
                "rawg_rating": 4.7,
                "metacritic": 87,
                "playtime_main": 6.0,
                "playtime_extra": 7.5,
                "playtime_completionist": 9.0,
                "user_playtime_minutes": 420, # 7 hours
                "rating_grade": "izumitelno",
                "user_score": 10,
                "user_review": "Изумительный пазл-платформер! Трогательная история, потрясающий визуал и музыка.",
                "notes": "Пройдено на 100% за пару вечеров. Идеально!",
                "is_favorite": 1,
                "priority": "low",
                "created_at": "2026-03-01T10:00:00",
                "started_at": "2026-03-02T18:00:00",
                "completed_at": "2026-03-05T22:30:00",
                "last_played_at": "2026-03-05T22:30:00"
            }
        ]

        for g in sample_games:
            game_uuid = str(uuid.uuid4())
            now_utc = datetime.now(timezone.utc).isoformat()
            cursor.execute('''
            INSERT INTO games (
                uuid, title, slug, rawg_id, cover_url, background_url, status,
                platform, platforms_list, genres, release_date, developer,
                publisher, rawg_rating, metacritic, playtime_main, playtime_extra,
                playtime_completionist, user_playtime_minutes, rating_grade, user_score,
                user_review, notes, is_favorite, priority, created_at,
                started_at, completed_at, last_played_at, updated_at, updated_by, client_created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                game_uuid,
                g["title"], g["slug"], g["rawg_id"], g["cover_url"], g["background_url"], g["status"],
                g["platform"], g["platforms_list"], g["genres"], g["release_date"], g["developer"],
                g["publisher"], g["rawg_rating"], g["metacritic"], g["playtime_main"], g["playtime_extra"],
                g["playtime_completionist"], g["user_playtime_minutes"], g.get("rating_grade", ""), g["user_score"],
                g["user_review"], g["notes"], g["is_favorite"], g["priority"], g["created_at"],
                g["started_at"], g["completed_at"], g["last_played_at"], now_utc, "system", g["created_at"]
            ))

        conn.commit()
    conn.close()

# --- CRUD Operations ---

def get_games(status: Optional[str] = None, platform: Optional[str] = None, 
              genre: Optional[str] = None, rating_grade: Optional[str] = None,
              search: Optional[str] = None, sort_by: str = "created_at_desc") -> List[Dict[str, Any]]:
    # Auto-seed if database has 0 games
    seed_initial_data_if_empty()

    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = "SELECT * FROM games WHERE 1=1"
    params = []
    
    if status and status != 'all':
        query += " AND status = ?"
        params.append(status)
        
    if platform and platform != 'all':
        query += " AND (platform LIKE ? OR platforms_list LIKE ?)"
        params.append(f"%{platform}%")
        params.append(f"%{platform}%")
        
    if genre and genre != 'all':
        query += " AND genres LIKE ?"
        params.append(f"%{genre}%")

    if rating_grade and rating_grade != 'all':
        query += " AND rating_grade = ?"
        params.append(rating_grade)
        
    if search:
        query += " AND (title LIKE ? OR developer LIKE ? OR publisher LIKE ? OR notes LIKE ? OR user_review LIKE ?)"
        term = f"%{search}%"
        params.extend([term, term, term, term, term])
        
    sort_mapping = {
        "created_at_desc": "id DESC",
        "created_at_asc": "id ASC",
        "title_asc": "title ASC",
        "title_desc": "title DESC",
        "playtime_asc": "playtime_main ASC",
        "playtime_desc": "playtime_main DESC",
        "user_playtime_desc": "user_playtime_minutes DESC",
        "user_playtime_asc": "user_playtime_minutes ASC",
        "release_date_desc": "release_date DESC",
        "release_date_asc": "release_date ASC",
        "rating_desc": "rawg_rating DESC",
        "grade_desc": "CASE rating_grade WHEN 'izumitelno' THEN 1 WHEN 'pohvalno' THEN 2 WHEN 'prohodnyak' THEN 3 WHEN 'musor' THEN 4 ELSE 5 END",
        "priority_desc": "CASE priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 WHEN 'low' THEN 4 ELSE 5 END"
    }
    
    order_clause = sort_mapping.get(sort_by, "id DESC")
    query += f" ORDER BY {order_clause}"
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["platforms_list"] = json.loads(d.get("platforms_list") or "[]")
        except Exception:
            d["platforms_list"] = [d.get("platform", "PC")]
        result.append(d)
    return result

def get_game_by_id(game_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM games WHERE id = ?", (game_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    try:
        d["platforms_list"] = json.loads(d.get("platforms_list") or "[]")
    except Exception:
        d["platforms_list"] = [d.get("platform", "PC")]
    return d

def get_game_by_uuid(game_uuid: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM games WHERE uuid = ?", (game_uuid,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    try:
        d["platforms_list"] = json.loads(d.get("platforms_list") or "[]")
    except Exception:
        d["platforms_list"] = [d.get("platform", "PC")]
    return d

def create_game(game_data: Dict[str, Any]) -> Dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()
    now_utc_str = datetime.now(timezone.utc).isoformat()
    
    game_uuid = game_data.get("uuid") or str(uuid.uuid4())
    updated_at = game_data.get("updated_at") or now_utc_str
    updated_by = game_data.get("updated_by") or "web-admin"
    client_created_at = game_data.get("client_created_at") or game_data.get("created_at") or now_utc_str
    created_at = game_data.get("created_at") or now_utc_str

    platforms_list_json = json.dumps(game_data.get("platforms_list") or [game_data.get("platform", "PC")])
    
    status = game_data.get("status", "backlog")
    started_at = game_data.get("started_at", "")
    if status == "playing" and not started_at:
        started_at = now_utc_str
        
    cursor.execute('''
    INSERT INTO games (
        uuid, title, slug, rawg_id, cover_url, background_url, status,
        platform, platforms_list, genres, release_date, developer,
        publisher, rawg_rating, metacritic, playtime_main, playtime_extra,
        playtime_completionist, user_playtime_minutes, rating_grade, user_score,
        user_review, notes, is_favorite, priority, created_at,
        started_at, completed_at, last_played_at, updated_at, updated_by, client_created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        game_uuid,
        game_data.get("title", "Untitled Game"),
        game_data.get("slug", ""),
        game_data.get("rawg_id"),
        game_data.get("cover_url", ""),
        game_data.get("background_url", ""),
        status,
        game_data.get("platform", "PC"),
        platforms_list_json,
        game_data.get("genres", ""),
        game_data.get("release_date", ""),
        game_data.get("developer", ""),
        game_data.get("publisher", ""),
        game_data.get("rawg_rating", 0.0),
        game_data.get("metacritic", 0),
        game_data.get("playtime_main", 0.0),
        game_data.get("playtime_extra", 0.0),
        game_data.get("playtime_completionist", 0.0),
        game_data.get("user_playtime_minutes", 0),
        game_data.get("rating_grade", ""),
        game_data.get("user_score", 0),
        game_data.get("user_review", ""),
        game_data.get("notes", ""),
        game_data.get("is_favorite", 0),
        game_data.get("priority", "medium"),
        created_at,
        started_at,
        game_data.get("completed_at", ""),
        now_utc_str if status == "playing" else "",
        updated_at,
        updated_by,
        client_created_at
    ))
    
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return get_game_by_id(new_id)

def update_game(game_id: int, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    current = get_game_by_id(game_id)
    if not current:
        conn.close()
        return None
        
    now_utc_str = datetime.now(timezone.utc).isoformat()
    
    new_status = updates.get("status")
    if new_status and new_status != current["status"]:
        if new_status == "playing" and not current.get("started_at"):
            updates["started_at"] = now_utc_str
        elif new_status == "completed" and not current.get("completed_at"):
            updates["completed_at"] = now_utc_str
        elif new_status != "completed" and current["status"] == "completed":
            updates["completed_at"] = ""
            
    if "platforms_list" in updates and isinstance(updates["platforms_list"], list):
        updates["platforms_list"] = json.dumps(updates["platforms_list"])

    # Always ensure updated_at and updated_by are tracked
    if "updated_at" not in updates or not updates["updated_at"]:
        updates["updated_at"] = now_utc_str
    if "updated_by" not in updates or not updates["updated_by"]:
        updates["updated_by"] = "web-admin"
        
    set_clauses = []
    params = []
    for k, v in updates.items():
        if v is not None and k != "id":
            set_clauses.append(f"{k} = ?")
            params.append(v)
            
    if not set_clauses:
        conn.close()
        return current
        
    query = f"UPDATE games SET {', '.join(set_clauses)} WHERE id = ?"
    params.append(game_id)
    
    cursor.execute(query, params)
    conn.commit()
    conn.close()
    return get_game_by_id(game_id)

def update_game_by_uuid(game_uuid: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    current = get_game_by_uuid(game_uuid)
    if not current:
        return None
    return update_game(current["id"], updates)

def delete_game(game_id: int, deleted_by: str = "web-admin") -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT uuid, title FROM games WHERE id = ?", (game_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False
        
    game_uuid = row["uuid"]
    title = row["title"] or ""
    now_utc_str = datetime.now(timezone.utc).isoformat()
    
    cursor.execute("DELETE FROM games WHERE id = ?", (game_id,))
    deleted = cursor.rowcount > 0
    
    if deleted and game_uuid:
        cursor.execute(
            "INSERT OR REPLACE INTO sync_tombstones (uuid, deleted_at, deleted_by, entity_type, title_backup) VALUES (?, ?, ?, 'game', ?)",
            (game_uuid, now_utc_str, deleted_by, title)
        )
        
    conn.commit()
    conn.close()
    return deleted

def delete_game_by_uuid(game_uuid: str, deleted_by: str = "web-admin", deleted_at: str = None) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, title FROM games WHERE uuid = ?", (game_uuid,))
    row = cursor.fetchone()
    
    now_utc_str = deleted_at or datetime.now(timezone.utc).isoformat()
    title = row["title"] if row else ""
    
    if row:
        cursor.execute("DELETE FROM games WHERE uuid = ?", (game_uuid,))
        
    cursor.execute(
        "INSERT OR REPLACE INTO sync_tombstones (uuid, deleted_at, deleted_by, entity_type, title_backup) VALUES (?, ?, ?, 'game', ?)",
        (game_uuid, now_utc_str, deleted_by, title)
    )
    conn.commit()
    conn.close()
    return True

def log_playtime(game_id: int, added_minutes: int, note: str = "") -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().isoformat()
    
    cursor.execute('''
    UPDATE games 
    SET user_playtime_minutes = MAX(0, user_playtime_minutes + ?),
        last_played_at = ?
    WHERE id = ?
    ''', (added_minutes, now_str, game_id))
    
    if cursor.rowcount == 0:
        conn.close()
        return None
        
    cursor.execute('''
    INSERT INTO play_sessions (game_id, duration_minutes, note, created_at)
    VALUES (?, ?, ?, ?)
    ''', (game_id, added_minutes, note, now_str))
    
    conn.commit()
    conn.close()
    return get_game_by_id(game_id)

def get_stats() -> Dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM games")
    total_games = cursor.fetchone()[0]
    
    cursor.execute("SELECT status, COUNT(*) FROM games GROUP BY status")
    status_counts = dict(cursor.fetchall())
    
    cursor.execute("SELECT SUM(user_playtime_minutes) FROM games")
    total_minutes_played = cursor.fetchone()[0] or 0
    
    cursor.execute("SELECT rating_grade, COUNT(*) FROM games WHERE status = 'completed' AND rating_grade != '' GROUP BY rating_grade")
    grade_counts = dict(cursor.fetchall())
    
    cursor.execute("SELECT platform, COUNT(*) FROM games GROUP BY platform ORDER BY COUNT(*) DESC LIMIT 8")
    platform_counts = dict(cursor.fetchall())

    cursor.execute("SELECT SUM(playtime_main) FROM games WHERE status = 'backlog'")
    backlog_total_hours = cursor.fetchone()[0] or 0.0

    cursor.execute("SELECT genres FROM games WHERE genres != ''")
    genre_rows = cursor.fetchall()
    genre_map = {}
    for r in genre_rows:
        for g in r[0].split(','):
            g_clean = g.strip()
            if g_clean:
                genre_map[g_clean] = genre_map.get(g_clean, 0) + 1
    top_genres = sorted(genre_map.items(), key=lambda x: x[1], reverse=True)[:8]

    conn.close()
    
    return {
        "total_games": total_games,
        "playing_count": status_counts.get("playing", 0),
        "backlog_count": status_counts.get("backlog", 0),
        "wishlist_count": status_counts.get("wishlist", 0),
        "completed_count": status_counts.get("completed", 0),
        "dropped_count": status_counts.get("dropped", 0),
        "paused_count": status_counts.get("paused", 0),
        "total_playtime_hours": round(total_minutes_played / 60.0, 1),
        "total_playtime_minutes": total_minutes_played,
        "backlog_total_hours": round(backlog_total_hours, 1),
        "grade_counts": {
            "izumitelno": grade_counts.get("izumitelno", 0),
            "pohvalno": grade_counts.get("pohvalno", 0),
            "prohodnyak": grade_counts.get("prohodnyak", 0),
            "musor": grade_counts.get("musor", 0)
        },
        "platform_counts": platform_counts,
        "top_genres": top_genres
    }

# --- Settings Operations ---

def get_all_settings() -> Dict[str, str]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM settings")
    rows = cursor.fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}

def get_setting(key: str, default: str = "") -> str:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row["value"] if row else default

def set_setting(key: str, value: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def save_settings_dict(settings_dict: Dict[str, str]):
    conn = get_db_connection()
    cursor = conn.cursor()
    for k, v in settings_dict.items():
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()

# --- AI History Operations ---

def get_ai_history(limit: int = 30) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT role, content, action_type, created_at FROM ai_history ORDER BY id ASC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def save_ai_message(role: str, content: str, action_type: str = "chat"):
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().isoformat()
    cursor.execute("INSERT INTO ai_history (role, content, action_type, created_at) VALUES (?, ?, ?, ?)", (role, content, action_type, now_str))
    conn.commit()
    conn.close()

def clear_ai_history():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM ai_history")
    conn.commit()
    conn.close()

# --- Full Database Dump & Restore for Backup (Single Bundle) ---

def export_full_database_json() -> Dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM games")
    games = [dict(r) for r in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM play_sessions")
    sessions = [dict(r) for r in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM settings")
    settings = [dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT * FROM ai_history")
    ai_history = [dict(r) for r in cursor.fetchall()]
    
    conn.close()
    
    return {
        "version": "3.0.0",
        "bundle_type": "gameroom_full_export",
        "exported_at": datetime.now().isoformat(),
        "games": games,
        "play_sessions": sessions,
        "settings": settings,
        "ai_history": ai_history
    }


MONTH_MAP = {
    "январь": "01", "февраль": "02", "март": "03", "апрель": "04",
    "май": "05", "июнь": "06", "июль": "07", "август": "08",
    "сентябрь": "09", "октябрь": "10", "ноябрь": "11", "декабрь": "12"
}

def parse_rating_to_grade(rating_str: str):
    if not rating_str or rating_str.strip() in ["-", ""]:
        return "", 0
    clean = str(rating_str).split("/")[0].strip()
    try:
        val = float(clean)
        score = int(round(val))
        if val >= 8.5:
            return "izumitelno", score
        elif val >= 6.8:
            return "pohvalno", score
        elif val >= 4.8:
            return "prohodnyak", score
        else:
            return "musor", score
    except:
        return "", 0

def normalize_platform(plat_str: str) -> str:
    if not plat_str:
        return "PC"
    p = plat_str.strip().lower()
    if "пк" in p or "pc" in p:
        return "PC"
    elif "switch" in p:
        return "Nintendo Switch"
    elif "quest" in p or "oculus" in p or "vr" in p:
        return "Meta Quest 3S VR"
    elif "playstation" in p or "ps5" in p or "ps4" in p:
        return "PlayStation 5"
    elif "xbox" in p:
        return "Xbox Series S/X"
    return plat_str.strip()

def normalize_status(status_str: str) -> str:
    if not status_str:
        return "wishlist"
    s = status_str.strip().lower()
    if "пройдено" in s or "completed" in s:
        return "completed"
    elif "в процессе" in s or "играю" in s or "playing" in s:
        return "playing"
    elif "брошено" in s or "dropped" in s:
        return "dropped"
    elif "пауз" in s or "paused" in s:
        return "paused"
    elif "бэклог" in s or "backlog" in s:
        return "backlog"
    return "wishlist"

def convert_legacy_backup_to_bundle(legacy_data: dict) -> dict:
    games_out = []
    ai_history_out = []
    
    # 1. Process legacy games list (Played, Dropped, Playing)
    for g in legacy_data.get("games", []):
        title = g.get("title", "").strip()
        if not title:
            continue
        
        status = normalize_status(g.get("status", ""))
        platform = normalize_platform(g.get("platform", ""))
        
        # Playtime
        time_val = g.get("time", "")
        playtime_minutes = 0
        if time_val:
            try:
                playtime_minutes = int(float(str(time_val).strip()) * 60)
            except:
                playtime_minutes = 0
        
        avg_playtime = g.get("avgPlaytime")
        playtime_main = 10.0
        if avg_playtime:
            try:
                playtime_main = float(avg_playtime)
            except:
                playtime_main = 10.0
                
        grade, score = parse_rating_to_grade(g.get("rating", ""))
        
        note = g.get("note", "").strip()
        ai_insight = g.get("aiInsight", "").strip()
        if ai_insight and not note:
            note = f"[AI Анализ]: {ai_insight[:120]}..."
        review = note if status == "completed" else ""
        
        year = g.get("year", "2026")
        month_num = MONTH_MAP.get(str(g.get("month", "")).lower(), "01")
        date_str = f"{year}-{month_num}-01T12:00:00"
        
        games_out.append({
            "title": title,
            "slug": "",
            "cover_url": g.get("coverUrl") or "",
            "background_url": g.get("coverUrl") or "",
            "status": status,
            "platform": platform,
            "platforms_list": json.dumps([platform]),
            "genres": "Экшен, Приключения",
            "release_date": f"{year}-{month_num}-01",
            "developer": "",
            "publisher": "",
            "rawg_rating": float(score) / 2.0 if score > 0 else 0.0,
            "metacritic": score * 10 if score > 0 else 0,
            "playtime_main": playtime_main,
            "playtime_extra": round(playtime_main * 1.35, 1),
            "playtime_completionist": round(playtime_main * 1.8, 1),
            "user_playtime_minutes": playtime_minutes,
            "rating_grade": grade,
            "user_score": score,
            "user_review": review,
            "notes": note,
            "is_favorite": 1 if grade == "izumitelno" or score >= 9 else 0,
            "priority": "high" if status == "playing" else "medium",
            "created_at": date_str,
            "started_at": date_str if status == "playing" else "",
            "completed_at": date_str if status == "completed" else "",
            "last_played_at": date_str
        })
        
    # 2. Process wishlist items
    for w in legacy_data.get("wishlist", []):
        title = w.get("title", "").strip()
        if not title:
            continue
            
        platform = normalize_platform(w.get("platform", ""))
        
        avg_playtime = w.get("avgPlaytime")
        playtime_main = 10.0
        if avg_playtime:
            try:
                playtime_main = float(avg_playtime)
            except:
                playtime_main = 10.0
                
        year = w.get("expectedYear", "2025")
        month_num = MONTH_MAP.get(str(w.get("expectedMonth", "")).lower(), "01")
        date_str = f"{year}-{month_num}-01"
        
        games_out.append({
            "title": title,
            "slug": "",
            "cover_url": "",
            "background_url": "",
            "status": "backlog",
            "platform": platform,
            "platforms_list": json.dumps([platform]),
            "genres": "Игры",
            "release_date": date_str,
            "developer": "",
            "publisher": "",
            "rawg_rating": 0.0,
            "metacritic": 0,
            "playtime_main": playtime_main,
            "playtime_extra": round(playtime_main * 1.35, 1),
            "playtime_completionist": round(playtime_main * 1.8, 1),
            "user_playtime_minutes": 0,
            "rating_grade": "",
            "user_score": 0,
            "user_review": "",
            "notes": w.get("note", ""),
            "is_favorite": 0,
            "priority": "medium",
            "created_at": "2026-09-01T12:00:00",
            "started_at": "",
            "completed_at": "",
            "last_played_at": ""
        })
        
    # 3. Process playedList legacy strings
    existing_titles = {g["title"].lower() for g in games_out}
    for title in legacy_data.get("playedList", []):
        clean_t = str(title).strip()
        if clean_t and clean_t.lower() not in existing_titles:
            games_out.append({
                "title": clean_t,
                "slug": "",
                "cover_url": "",
                "background_url": "",
                "status": "completed",
                "platform": "PC",
                "platforms_list": json.dumps(["PC"]),
                "genres": "Игры",
                "release_date": "",
                "developer": "",
                "publisher": "",
                "rawg_rating": 4.5,
                "metacritic": 85,
                "playtime_main": 12.0,
                "playtime_extra": 16.0,
                "playtime_completionist": 22.0,
                "user_playtime_minutes": 720,
                "rating_grade": "izumitelno",
                "user_score": 9,
                "user_review": "Пройдено ранее.",
                "notes": "Импортировано из истории прохождений.",
                "is_favorite": 1,
                "priority": "medium",
                "created_at": "2026-01-01T12:00:00",
                "started_at": "",
                "completed_at": "2026-01-01T12:00:00",
                "last_played_at": "2026-01-01T12:00:00"
            })
            existing_titles.add(clean_t.lower())
            
    # 4. Process AI messages & Month Summary
    if legacy_data.get("aiMessage"):
        ai_history_out.append({
            "role": "assistant",
            "content": f"🧠 **Архивный портрет геймера (Импортировано):**\n\n{legacy_data['aiMessage']}",
            "action_type": "portrait",
            "created_at": "2026-09-01T12:00:00"
        })
        
    if legacy_data.get("monthSummary") and isinstance(legacy_data["monthSummary"], dict):
        m_txt = legacy_data["monthSummary"].get("text", "")
        if m_txt:
            ai_history_out.append({
                "role": "assistant",
                "content": f"📅 **Итоги месяца ({legacy_data['monthSummary'].get('month')} {legacy_data['monthSummary'].get('year')}):**\n\n{m_txt}",
                "action_type": "summary",
                "created_at": "2026-09-01T12:00:00"
            })
            
    return {
        "version": "3.0.0",
        "bundle_type": "gameroom_full_export",
        "games": games_out,
        "play_sessions": [],
        "settings": [],
        "ai_history": ai_history_out
    }

def import_full_database_json(data: Dict[str, Any]) -> Dict[str, Any]:
    # Check if legacy format from previous app
    if "wishlist" in data or "playedList" in data or ("games" in data and any("coverUrl" in g or "avgPlaytime" in g or "month" in g for g in data["games"])):
        data = convert_legacy_backup_to_bundle(data)

    conn = get_db_connection()
    cursor = conn.cursor()
    
    imported_games = 0
    imported_sessions = 0
    imported_settings = 0
    imported_ai = 0
    
    # 1. Import games
    for g in data.get("games", []):
        cursor.execute('''
        INSERT OR REPLACE INTO games (
            id, title, slug, rawg_id, cover_url, background_url, status,
            platform, platforms_list, genres, release_date, developer,
            publisher, rawg_rating, metacritic, playtime_main, playtime_extra,
            playtime_completionist, user_playtime_minutes, rating_grade, user_score,
            user_review, notes, is_favorite, priority, created_at,
            started_at, completed_at, last_played_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        ''', (
            g.get("id"), g.get("title", ""), g.get("slug", ""), g.get("rawg_id"),
            g.get("cover_url", ""), g.get("background_url", ""), g.get("status", "backlog"),
            g.get("platform", "PC"), g.get("platforms_list", "[]"), g.get("genres", ""),
            g.get("release_date", ""), g.get("developer", ""), g.get("publisher", ""),
            g.get("rawg_rating", 0.0), g.get("metacritic", 0), g.get("playtime_main", 0.0),
            g.get("playtime_extra", 0.0), g.get("playtime_completionist", 0.0),
            g.get("user_playtime_minutes", 0), g.get("rating_grade", ""), g.get("user_score", 0),
            g.get("user_review", ""), g.get("notes", ""), g.get("is_favorite", 0), g.get("priority", "medium"),
            g.get("created_at", ""), g.get("started_at", ""), g.get("completed_at", ""),
            g.get("last_played_at", "")
        ))
        imported_games += 1
        
    # 2. Import play sessions
    for s in data.get("play_sessions", []):
        cursor.execute('''
        INSERT OR REPLACE INTO play_sessions (id, game_id, duration_minutes, note, created_at)
        VALUES (?, ?, ?, ?, ?)
        ''', (s.get("id"), s.get("game_id"), s.get("duration_minutes", 0), s.get("note", ""), s.get("created_at", "")))
        imported_sessions += 1

    # 3. Import settings
    for st in data.get("settings", []):
        if isinstance(st, dict) and "key" in st and "value" in st:
            cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (st["key"], st["value"]))
            imported_settings += 1

    # 4. Import AI history
    for ai in data.get("ai_history", []):
        cursor.execute('''
        INSERT OR REPLACE INTO ai_history (id, role, content, action_type, created_at)
        VALUES (?, ?, ?, ?, ?)
        ''', (ai.get("id"), ai.get("role", "user"), ai.get("content", ""), ai.get("action_type", "chat"), ai.get("created_at", datetime.now().isoformat())))
        imported_ai += 1
        
    conn.commit()
    conn.close()
    return {
        "success": True,
        "imported_games": imported_games,
        "imported_sessions": imported_sessions,
        "imported_settings": imported_settings,
        "imported_ai_history": imported_ai
    }


def move_games_status(from_status: str, to_status: str) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE games SET status = ? WHERE status = ?", (to_status, from_status))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected

def clear_games_status(status: str) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM games WHERE status = ?", (status,))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected
