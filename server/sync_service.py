"""
Distributed Synchronization Service for GAME-ROOM's Backlog Application
Implements Delta-Sync, LWW conflict resolution with time skew compensation,
Category A/B field preservation, tombstone tracking, and Initial Sync deduplication.
"""
import re
import json
import uuid as py_uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple

import database as db
from models import (
    SyncRequest, SyncResponse, SyncAck, SyncServerChanges,
    InitialSyncRequest, InitialSyncResponse, SyncItemIn
)

# --- Normalization Helpers ---

PLATFORM_MAP = {
    "домашний пк": "PC",
    "рабочий пк": "PC",
    "домашний": "PC",
    "пк": "PC",
    "pc": "PC",
    "компьютер": "PC",
    "steam": "PC",
    "nintendo switch": "Nintendo Switch",
    "switch": "Nintendo Switch",
    "свитч": "Nintendo Switch",
    "meta quest 3s vr": "Meta Quest 3S VR",
    "oculus quest 3s": "Meta Quest 3S VR",
    "oculus quest 2": "Meta Quest 3S VR",
    "oculus quest": "Meta Quest 3S VR",
    "quest 3s": "Meta Quest 3S VR",
    "quest": "Meta Quest 3S VR",
    "playstation 5": "PlayStation 5",
    "ps5": "PlayStation 5",
    "playstation 4": "PlayStation 4",
    "ps4": "PlayStation 4",
    "playstation": "PlayStation 5",
    "xbox series s/x": "Xbox Series S/X",
    "xbox series x": "Xbox Series S/X",
    "xbox series s": "Xbox Series S/X",
    "xbox": "Xbox Series S/X"
}

def normalize_platform(plat_str: str) -> str:
    if not plat_str:
        return "PC"
    clean = plat_str.strip().lower()
    return PLATFORM_MAP.get(clean, plat_str.strip())

def normalize_title(title: str) -> str:
    if not title:
        return ""
    # Lowercase, strip punctuation and whitespace for fuzzy comparison
    return re.sub(r'[^a-zA-Z0-9\u0400-\u04FF]+', '', title.lower()).strip()

def normalize_status(status_str: str) -> str:
    if not status_str:
        return "backlog"
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
    elif "вишлист" in s or "wishlist" in s:
        return "wishlist"
    return "backlog"

def parse_rating_to_grade(rating_str: str) -> Tuple[str, int]:
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
    except Exception:
        return "", 0

def parse_iso_dt(dt_str: Optional[str]) -> Optional[datetime]:
    if not dt_str or not isinstance(dt_str, str):
        return None
    try:
        clean = dt_str.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None

def calculate_effective_updated_at(item_updated_at: str, client_now_str: str, server_now_dt: datetime) -> str:
    """
    Calculates effective_updated_at using relative offset to compensate for client clock skew:
    delta_t = client_now - item_updated_at
    effective_updated_at = server_now - delta_t
    """
    if not item_updated_at:
        return server_now_dt.isoformat()
    if not client_now_str:
        return item_updated_at
    try:
        c_now = datetime.fromisoformat(client_now_str.replace("Z", "+00:00"))
        c_item = datetime.fromisoformat(item_updated_at.replace("Z", "+00:00"))
        delta_seconds = max(0.0, (c_now - c_item).total_seconds())
        effective_dt = server_now_dt - timedelta(seconds=delta_seconds)
        return effective_dt.isoformat()
    except Exception:
        return item_updated_at

# --- Core Synchronization Logic ---

def process_sync(req: SyncRequest) -> SyncResponse:
    server_now_dt = datetime.now(timezone.utc)
    server_time_str = server_now_dt.isoformat()
    client_id = req.client_id
    client_now_str = req.client_time_now or ""
    last_sync_timestamp = req.last_sync_timestamp or ""

    ack = SyncAck()
    server_changes = SyncServerChanges()
    conn = db.get_db_connection()
    cursor = conn.cursor()

    try:
        # 1. Unify all operations and execute strictly by client_seq
        all_ops = []
        for d in req.changes.deleted:
            all_ops.append(("delete", d, d.client_seq or 0))
        for c in req.changes.created:
            all_ops.append(("create", c, c.client_seq or 0))
        for u in req.changes.updated:
            all_ops.append(("update", u, u.client_seq or 0))

        all_ops.sort(key=lambda x: x[2])

        conflict_server_wins_uuids = set()

        for op_type, item, op_seq in all_ops:
            item_uuid = item.uuid
            if not item_uuid:
                continue

            if op_type == "delete":
                effective_del_time = calculate_effective_updated_at(item.deleted_at, client_now_str, server_now_dt)
                existing = db.get_game_by_uuid(item_uuid)

                # Check if server version was updated after client deleted it (newer update beats older delete)
                if existing:
                    existing_updated_at = existing.get("updated_at") or ""
                    if existing_updated_at and effective_del_time < existing_updated_at:
                        # Server version is newer: keep server record, reject delete
                        ack.conflicts_resolved += 1
                        ack.applied_deleted.append(item_uuid)
                        conflict_server_wins_uuids.add(item_uuid)
                        continue

                # Check if already tombstoned with newer deletion timestamp
                cursor.execute("SELECT deleted_at FROM sync_tombstones WHERE uuid = ?", (item_uuid,))
                tomb = cursor.fetchone()
                if tomb and tomb["deleted_at"] >= effective_del_time:
                    ack.applied_deleted.append(item_uuid)
                    continue

                db.delete_game_by_uuid(item_uuid, deleted_by=client_id, deleted_at=effective_del_time)
                ack.applied_deleted.append(item_uuid)
                continue

            # Create or Update operation
            is_create_intent = (op_type == "create")
            effective_updated_at = calculate_effective_updated_at(item.updated_at, client_now_str, server_now_dt)
            existing = db.get_game_by_uuid(item_uuid)

            if existing:
                # Conflict Resolution: LWW by effective_updated_at
                existing_updated_at = existing.get("updated_at") or ""
                existing_dt = parse_iso_dt(existing_updated_at)
                effective_dt = parse_iso_dt(effective_updated_at)
                last_sync_dt = parse_iso_dt(last_sync_timestamp)

                # A conflict only exists if the server was modified after client's last sync
                server_modified_since_last_sync = False
                if existing_dt:
                    if last_sync_dt:
                        if (existing_dt - last_sync_dt).total_seconds() > 1.0:
                            server_modified_since_last_sync = True
                    else:
                        server_modified_since_last_sync = True

                if server_modified_since_last_sync and existing_dt and effective_dt and effective_dt < existing_dt:
                    # Server version is genuinely newer: keep server version and mark for return to client
                    ack.conflicts_resolved += 1
                    ack.applied_updated.append(item_uuid)
                    conflict_server_wins_uuids.add(item_uuid)
                    continue

                # Prepare updates preserving Category B fields
                norm_plat = normalize_platform(item.platform)
                norm_status = normalize_status(item.status)

                # Rating preservation & update
                if item.user_score is not None and item.user_score > 0:
                    final_score = item.user_score
                    calc_grade, _ = parse_rating_to_grade(f"{final_score}/10")
                    final_grade = calc_grade if calc_grade else (item.rating_grade or "")
                elif item.rating_grade:
                    final_grade = item.rating_grade
                    final_score = db.grade_to_score(final_grade, existing.get("user_score"))
                elif item.user_score == 0 or item.rating_grade == "":
                    final_score = 0
                    final_grade = ""
                else:
                    final_score = existing.get("user_score") or 0
                    final_grade = item.rating_grade or existing.get("rating_grade") or ""
                    if not final_grade and final_score > 0:
                        final_grade, _ = parse_rating_to_grade(f"{final_score}/10")

                # Partial patch update for Category A fields
                patch_data = {
                    "title": item.title or existing.get("title"),
                    "status": norm_status,
                    "platform": norm_plat,
                    "user_playtime_minutes": item.user_playtime_minutes if item.user_playtime_minutes is not None else existing.get("user_playtime_minutes", 0),
                    "rating_grade": final_grade,
                    "user_score": final_score,
                    "notes": item.notes if item.notes is not None else existing.get("notes", ""),
                    "user_review": item.user_review if item.user_review is not None else existing.get("user_review", ""),
                    "completed_at": item.completed_at if item.completed_at is not None else existing.get("completed_at", ""),
                    "is_favorite": item.is_favorite if item.is_favorite is not None else existing.get("is_favorite", 0),
                    "priority": item.priority or existing.get("priority", "medium"),
                    "updated_at": effective_updated_at,
                    "updated_by": client_id
                }

                # Only update Category B fields if provided and not empty
                if item.rawg_id:
                    patch_data["rawg_id"] = item.rawg_id
                if item.cover_url:
                    patch_data["cover_url"] = item.cover_url
                if item.background_url:
                    patch_data["background_url"] = item.background_url
                if item.genres:
                    patch_data["genres"] = item.genres
                if item.developer:
                    patch_data["developer"] = item.developer
                if item.publisher:
                    patch_data["publisher"] = item.publisher
                if item.playtime_main is not None and item.playtime_main > 0:
                    if item.playtime_main != existing.get("playtime_main"):
                        patch_data["playtime_main"] = item.playtime_main
                        patch_data["playtime_source"] = "manual"

                db.update_game_by_uuid(item_uuid, patch_data)
                ack.applied_updated.append(item_uuid)
            else:
                # Check if item was deleted on server (tombstone exists)
                cursor.execute("SELECT deleted_at, deleted_by FROM sync_tombstones WHERE uuid = ?", (item_uuid,))
                tomb = cursor.fetchone()
                if tomb:
                    tomb_del_at = tomb["deleted_at"]
                    # If it was an update intent or if client modification happened before deletion: tombstone wins
                    if not is_create_intent or effective_updated_at <= tomb_del_at:
                        ack.conflicts_resolved += 1
                        if is_create_intent:
                            ack.applied_created.append(item_uuid)
                        else:
                            ack.applied_updated.append(item_uuid)
                        # Notify client about tombstone so it removes it locally
                        server_changes.deleted.append({
                            "uuid": item_uuid,
                            "deleted_at": tomb_del_at
                        })
                        continue
                    else:
                        # Client deliberately created item anew with same UUID after deletion
                        cursor.execute("DELETE FROM sync_tombstones WHERE uuid = ?", (item_uuid,))
                        conn.commit()

                # Create new game
                norm_plat = normalize_platform(item.platform)
                norm_status = normalize_status(item.status)
                final_grade = item.rating_grade or ""
                final_score = item.user_score or 0
                if final_score > 0:
                    calc_grade, _ = parse_rating_to_grade(f"{final_score}/10")
                    final_grade = calc_grade if calc_grade else final_grade
                elif final_grade:
                    final_score = db.grade_to_score(final_grade)

                new_game_dict = {
                    "uuid": item_uuid,
                    "title": item.title,
                    "slug": item.slug or "",
                    "rawg_id": item.rawg_id,
                    "cover_url": item.cover_url or "",
                    "background_url": item.background_url or "",
                    "status": norm_status,
                    "platform": norm_plat,
                    "platforms_list": item.platforms_list or [norm_plat],
                    "genres": item.genres or "",
                    "release_date": item.release_date or "",
                    "developer": item.developer or "",
                    "publisher": item.publisher or "",
                    "rawg_rating": item.rawg_rating or 0.0,
                    "metacritic": item.metacritic or 0,
                    "playtime_main": item.playtime_main or 0.0,
                    "playtime_extra": item.playtime_extra or 0.0,
                    "playtime_completionist": item.playtime_completionist or 0.0,
                    "user_playtime_minutes": item.user_playtime_minutes or 0,
                    "rating_grade": final_grade,
                    "user_score": final_score,
                    "user_review": item.user_review or "",
                    "notes": item.notes or "",
                    "is_favorite": item.is_favorite or 0,
                    "priority": item.priority or "medium",
                    "created_at": item.created_at or effective_updated_at,
                    "started_at": item.started_at or "",
                    "completed_at": item.completed_at or "",
                    "updated_at": effective_updated_at,
                    "updated_by": client_id,
                    "client_created_at": item.created_at or effective_updated_at
                }
                db.create_game(new_game_dict)
                ack.applied_created.append(item_uuid)

        # 3. Pull Server Changes (since last_sync_timestamp)
        if last_sync_timestamp:
            # Query updated/created games on server not made by this client
            cursor.execute('''
            SELECT * FROM games 
            WHERE updated_at > ? AND (updated_by != ? OR updated_by IS NULL)
            ''', (last_sync_timestamp, client_id))
            server_game_rows = cursor.fetchall()
            for r in server_game_rows:
                g = dict(r)
                try:
                    g["platforms_list"] = json.loads(g.get("platforms_list") or "[]")
                except Exception:
                    g["platforms_list"] = [g.get("platform", "PC")]
                # Don't include items that were just applied from this client in this transaction,
                # UNLESS the server won a conflict and needs to send the winning server state to the client!
                is_applied_by_client = (g.get("uuid") in ack.applied_created or g.get("uuid") in ack.applied_updated)
                if not is_applied_by_client or g.get("uuid") in conflict_server_wins_uuids:
                    server_changes.updated.append(g)

            # Ensure all winning server games are present in server_changes.updated
            for win_uuid in conflict_server_wins_uuids:
                if not any(sg.get("uuid") == win_uuid for sg in server_changes.updated):
                    win_game = db.get_game_by_uuid(win_uuid)
                    if win_game:
                        try:
                            win_game["platforms_list"] = json.loads(win_game.get("platforms_list") or "[]")
                        except Exception:
                            win_game["platforms_list"] = [win_game.get("platform", "PC")]
                        server_changes.updated.append(win_game)

            # Query tombstones on server not deleted by this client
            cursor.execute('''
            SELECT uuid, deleted_at, deleted_by, title_backup FROM sync_tombstones
            WHERE deleted_at > ? AND (deleted_by != ? OR deleted_by IS NULL)
            ''', (last_sync_timestamp, client_id))
            tombstone_rows = cursor.fetchall()
            for t in tombstone_rows:
                if t["uuid"] not in ack.applied_deleted and not any(d.get("uuid") == t["uuid"] for d in server_changes.deleted):
                    server_changes.deleted.append({
                        "uuid": t["uuid"],
                        "deleted_at": t["deleted_at"]
                    })
        else:
            # Initial pull: return all server games
            cursor.execute("SELECT * FROM games")
            for r in cursor.fetchall():
                g = dict(r)
                try:
                    g["platforms_list"] = json.loads(g.get("platforms_list") or "[]")
                except Exception:
                    g["platforms_list"] = [g.get("platform", "PC")]
                if g.get("uuid") not in ack.applied_created and g.get("uuid") not in ack.applied_updated:
                    server_changes.created.append(g)

    finally:
        conn.close()

    return SyncResponse(
        success=True,
        server_time=server_time_str,
        client_id=client_id,
        ack=ack,
        server_changes=server_changes
    )

# --- Initial Sync Deduplication Logic ---

def extract_year(date_or_year: Any) -> Optional[int]:
    if not date_or_year:
        return None
    s = str(date_or_year).strip()
    match = re.search(r'\b(19\d\d|20\d\d)\b', s)
    if match:
        return int(match.group(1))
    return None

def process_initial_sync(req: InitialSyncRequest) -> InitialSyncResponse:
    """
    Performs safe initial merge of existing Android database with server database.
    Deduplication rules:
    Level 1: Match by rawg_id > 0
    Level 2: Match by exact normalized title + normalized platform + release year (+-1 year)
    Level 3: If no reliable match, DO NOT merge — create separate entry with new UUID.
    """
    server_now_dt = datetime.now(timezone.utc)
    server_time_str = server_now_dt.isoformat()
    client_id = req.client_id

    conn = db.get_db_connection()
    cursor = conn.cursor()

    merged_count = 0
    created_count = 0

    try:
        # Load all existing server games for fast in-memory lookup
        cursor.execute("SELECT * FROM games")
        server_games = [dict(r) for r in cursor.fetchall()]

        # Prepare lookup indexes
        rawg_index = {}
        uuid_index = {}
        for sg in server_games:
            rid = sg.get("rawg_id")
            if rid and int(rid) > 0:
                rawg_index[int(rid)] = sg
            u = sg.get("uuid")
            if u:
                uuid_index[str(u).strip()] = sg

        # Combine Android games and wishlist
        incoming_items = []
        for g in req.games:
            incoming_items.append((g, "game"))
        for w in req.wishlist:
            incoming_items.append((w, "wishlist"))

        for item, source_kind in incoming_items:
            raw_title = str(item.get("title", "")).strip()
            if not raw_title:
                continue

            raw_rawg_id = item.get("rawg_id")
            incoming_rawg_id = int(raw_rawg_id) if raw_rawg_id and str(raw_rawg_id).isdigit() and int(raw_rawg_id) > 0 else None
            incoming_norm_title = normalize_title(raw_title)
            incoming_platform = normalize_platform(item.get("platform", "PC"))
            incoming_year = extract_year(item.get("year") or item.get("expectedYear") or item.get("release_date"))

            matched_server_game = None

            # Level 0: Match by UUID (highest precision)
            incoming_uuid = str(item.get("uuid") or "").strip()
            if incoming_uuid and incoming_uuid in uuid_index:
                matched_server_game = uuid_index[incoming_uuid]

            # Level 1: Match by rawg_id
            if not matched_server_game and incoming_rawg_id and incoming_rawg_id in rawg_index:
                matched_server_game = rawg_index[incoming_rawg_id]

            # Level 2: Match by normalized title + platform + year (+-1)
            if not matched_server_game:
                for sg in server_games:
                    sg_norm_title = normalize_title(sg.get("title", ""))
                    sg_norm_plat = normalize_platform(sg.get("platform", ""))
                    if incoming_norm_title == sg_norm_title and incoming_platform == sg_norm_plat:
                        sg_year = extract_year(sg.get("release_date") or sg.get("created_at"))
                        # If years are known, enforce +-1 year difference; if unknown, only match if title is distinctive (>3 chars)
                        if incoming_year and sg_year:
                            if abs(incoming_year - sg_year) <= 1:
                                matched_server_game = sg
                                break
                        elif len(incoming_norm_title) >= 4:
                            matched_server_game = sg
                            break

            # Convert playtime hours to minutes if provided as 'time'
            time_val = item.get("time")
            user_minutes = item.get("user_playtime_minutes")
            if user_minutes is None and time_val:
                try:
                    user_minutes = int(round(float(str(time_val).strip()) * 60))
                except Exception:
                    user_minutes = 0
            user_minutes = user_minutes or 0

            # Convert rating
            rating_grade = item.get("rating_grade") or ""
            user_score = item.get("user_score") or 0
            if not rating_grade and item.get("rating"):
                g_grade, g_score = parse_rating_to_grade(str(item.get("rating")))
                rating_grade = g_grade
                if user_score == 0:
                    user_score = g_score

            status = normalize_status(item.get("status") or ("backlog" if source_kind == "wishlist" else "playing"))

            if matched_server_game:
                # Merge into existing server game
                server_game_id = matched_server_game["id"]
                server_minutes = matched_server_game.get("user_playtime_minutes") or 0
                max_playtime = max(server_minutes, user_minutes)

                patch = {
                    "user_playtime_minutes": max_playtime,
                    "updated_at": server_time_str,
                    "updated_by": client_id
                }
                if not matched_server_game.get("notes") and item.get("note"):
                    patch["user_review"] = item.get("note")
                if not matched_server_game.get("rating_grade") and rating_grade:
                    patch["rating_grade"] = rating_grade
                if (not matched_server_game.get("user_score") or matched_server_game.get("user_score") == 0) and user_score > 0:
                    patch["user_score"] = user_score

                db.update_game(server_game_id, patch)
                merged_count += 1
            else:
                # Level 3: No safe match -> Create new record with item's UUID or new UUID
                item_uuid = item.get("uuid") or str(py_uuid.uuid4())
                new_record = {
                    "uuid": item_uuid,
                    "title": raw_title,
                    "slug": item.get("slug", ""),
                    "rawg_id": incoming_rawg_id,
                    "cover_url": item.get("coverUrl") or item.get("cover_url", ""),
                    "background_url": item.get("coverUrl") or item.get("background_url", ""),
                    "status": status,
                    "platform": incoming_platform,
                    "platforms_list": [incoming_platform],
                    "genres": item.get("genres", ""),
                    "release_date": f"{incoming_year}-01-01" if incoming_year else "",
                    "developer": item.get("developer", ""),
                    "publisher": item.get("publisher", ""),
                    "rawg_rating": float(user_score) / 2.0 if user_score > 0 else 0.0,
                    "metacritic": user_score * 10 if user_score > 0 else 0,
                    "playtime_main": float(item.get("avgPlaytime") or 0.0),
                    "playtime_source": "manual" if float(item.get("avgPlaytime") or 0.0) > 0 else "legacy",
                    "playtime_extra": round(float(item.get("avgPlaytime") or 0.0) * 1.35, 1),
                    "playtime_completionist": round(float(item.get("avgPlaytime") or 0.0) * 1.8, 1),
                    "user_playtime_minutes": user_minutes,
                    "rating_grade": rating_grade,
                    "user_score": user_score,
                    "user_review": item.get("note", "") if status == "completed" else "",
                    "notes": "",
                    "is_favorite": 1 if rating_grade == "izumitelno" or user_score >= 9 else 0,
                    "priority": "medium",
                    "created_at": server_time_str,
                    "started_at": item.get("started_at") or (server_time_str if status == "playing" else ""),
                    "completed_at": item.get("completed_at") or (server_time_str if status == "completed" else ""),
                    "last_played_at": server_time_str if status == "playing" else "",
                    "updated_at": server_time_str,
                    "updated_by": client_id,
                    "client_created_at": server_time_str
                }
                created_record = db.create_game(new_record)
                server_games.append(created_record)
                if incoming_rawg_id:
                    rawg_index[incoming_rawg_id] = created_record
                created_count += 1

    finally:
        conn.close()

    # Return full master list of games from server
    full_games = db.get_games()

    return InitialSyncResponse(
        success=True,
        server_time=server_time_str,
        client_id=client_id,
        merged_count=merged_count,
        created_count=created_count,
        games=full_games
    )
