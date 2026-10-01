"""
Data models for GAME-ROOM's Backlog Application
"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class GameCreate(BaseModel):
    title: str
    slug: Optional[str] = ""
    rawg_id: Optional[int] = None
    cover_url: Optional[str] = ""
    background_url: Optional[str] = ""
    status: str = "backlog"  # 'playing', 'backlog', 'wishlist', 'completed', 'dropped', 'paused'
    platform: Optional[str] = "PC"
    platforms_list: Optional[List[str]] = []
    genres: Optional[str] = ""
    release_date: Optional[str] = ""
    developer: Optional[str] = ""
    publisher: Optional[str] = ""
    rawg_rating: Optional[float] = 0.0
    metacritic: Optional[int] = 0
    playtime_main: Optional[float] = 0.0  # Estimated hours for main story
    playtime_extra: Optional[float] = 0.0  # Estimated hours main + extras
    playtime_completionist: Optional[float] = 0.0  # Estimated hours 100%
    user_playtime_minutes: Optional[int] = 0  # Actual played time in minutes
    rating_grade: Optional[str] = ""  # 'izumitelno', 'pohvalno', 'prohodnyak', 'musor', or ''
    user_score: Optional[int] = 0  # 1-10 fallback
    user_review: Optional[str] = ""
    notes: Optional[str] = ""
    is_favorite: Optional[int] = 0
    priority: Optional[str] = "medium"  # 'low', 'medium', 'high', 'urgent'
    started_at: Optional[str] = ""
    completed_at: Optional[str] = ""

class GameUpdate(BaseModel):
    title: Optional[str] = None
    slug: Optional[str] = None
    rawg_id: Optional[int] = None
    cover_url: Optional[str] = None
    background_url: Optional[str] = None
    status: Optional[str] = None
    platform: Optional[str] = None
    platforms_list: Optional[List[str]] = None
    genres: Optional[str] = None
    release_date: Optional[str] = None
    developer: Optional[str] = None
    publisher: Optional[str] = None
    rawg_rating: Optional[float] = None
    metacritic: Optional[int] = None
    playtime_main: Optional[float] = None
    playtime_extra: Optional[float] = None
    playtime_completionist: Optional[float] = None
    user_playtime_minutes: Optional[int] = None
    rating_grade: Optional[str] = None  # 'izumitelno', 'pohvalno', 'prohodnyak', 'musor', ''
    user_score: Optional[int] = None
    user_review: Optional[str] = None
    notes: Optional[str] = None
    is_favorite: Optional[int] = None
    priority: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

class QuickTimeUpdate(BaseModel):
    additional_minutes: int
    note: Optional[str] = ""

class SettingsUpdate(BaseModel):
    settings: Dict[str, str]

class ChatMessage(BaseModel):
    role: str  # 'user', 'assistant', 'system'
    content: str

class ChatRequest(BaseModel):
    message: str
    history: Optional[List[ChatMessage]] = []
    include_backlog_context: Optional[bool] = True
    action_type: Optional[str] = "chat"  # 'chat', 'portrait', 'suggest_next', 'tactical_advice', 'backlog_plan'

class QuickAddRawgRequest(BaseModel):
    rawg_id: Optional[int] = None
    slug: Optional[str] = None
    title: Optional[str] = ""
    target_status: str = "backlog"  # 'backlog', 'playing', 'wishlist'
    game_data: Optional[Dict[str, Any]] = None

class BackupRequest(BaseModel):
    note: Optional[str] = "Manual Backup"

class RestoreRequest(BaseModel):
    backup_path: str


class MoveStatusRequest(BaseModel):
    from_status: str
    to_status: str

class ClearStatusRequest(BaseModel):
    status: str

# --- Distributed Sync Models ---

class SyncItemIn(BaseModel):
    uuid: str
    client_seq: Optional[int] = 0
    title: str
    slug: Optional[str] = ""
    rawg_id: Optional[int] = None
    cover_url: Optional[str] = ""
    background_url: Optional[str] = ""
    status: str = "backlog"  # 'playing', 'backlog', 'wishlist', 'completed', 'dropped', 'paused'
    platform: Optional[str] = "PC"
    platforms_list: Optional[List[str]] = []
    genres: Optional[str] = ""
    release_date: Optional[str] = ""
    developer: Optional[str] = ""
    publisher: Optional[str] = ""
    rawg_rating: Optional[float] = 0.0
    metacritic: Optional[int] = 0
    playtime_main: Optional[float] = 0.0
    playtime_extra: Optional[float] = 0.0
    playtime_completionist: Optional[float] = 0.0
    user_playtime_minutes: Optional[int] = 0
    rating_grade: Optional[str] = ""
    user_score: Optional[int] = 0
    user_review: Optional[str] = ""
    notes: Optional[str] = ""
    is_favorite: Optional[int] = 0
    priority: Optional[str] = "medium"
    created_at: Optional[str] = ""
    started_at: Optional[str] = ""
    completed_at: Optional[str] = ""
    updated_at: Optional[str] = ""

class SyncDeletedItemIn(BaseModel):
    uuid: str
    deleted_at: Optional[str] = ""
    client_seq: Optional[int] = 0

class SyncChangesIn(BaseModel):
    created: List[SyncItemIn] = []
    updated: List[SyncItemIn] = []
    deleted: List[SyncDeletedItemIn] = []

class SyncRequest(BaseModel):
    client_id: str
    client_version: Optional[str] = "1.0"
    client_time_now: Optional[str] = ""
    last_sync_timestamp: Optional[str] = ""
    changes: SyncChangesIn = Field(default_factory=SyncChangesIn)

class SyncAck(BaseModel):
    applied_created: List[str] = []
    applied_updated: List[str] = []
    applied_deleted: List[str] = []
    conflicts_resolved: int = 0

class SyncServerChanges(BaseModel):
    created: List[Dict[str, Any]] = []
    updated: List[Dict[str, Any]] = []
    deleted: List[Dict[str, Any]] = []

class SyncResponse(BaseModel):
    success: bool = True
    server_time: str
    client_id: str
    ack: SyncAck
    server_changes: SyncServerChanges

class InitialSyncRequest(BaseModel):
    client_id: str
    client_time_now: Optional[str] = ""
    games: List[Dict[str, Any]] = []
    wishlist: List[Dict[str, Any]] = []

class InitialSyncResponse(BaseModel):
    success: bool = True
    server_time: str
    client_id: str
    merged_count: int = 0
    created_count: int = 0
    games: List[Dict[str, Any]] = []
