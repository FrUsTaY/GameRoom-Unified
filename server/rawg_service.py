"""
RAWG.io API Integration Service
Provides instant game search, automated metadata auto-fetch, cover arts,
Russian genre translation, release calendar dates, and playtime estimation
for seamless 1-click backlog additions.
"""
import os
import time
import requests
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from database import get_setting, create_game
from hltb_service import get_hltb_playtime

logger = logging.getLogger("rawg_service")
RAWG_BASE_URL = "https://api.rawg.io/api"

# Mapping of RAWG English genres & tags to Russian equivalents
GENRE_TRANSLATION_MAP = {
    "action": "Экшен",
    "adventure": "Приключения",
    "rpg": "Ролевая игра (RPG)",
    "role-playing-games-rpg": "Ролевая игра (RPG)",
    "shooter": "Шутер",
    "puzzle": "Головоломка",
    "platformer": "Платформер",
    "indie": "Инди",
    "strategy": "Стратегия",
    "simulation": "Симулятор",
    "racing": "Гонки",
    "fighting": "Файтинг",
    "arcade": "Аркада",
    "casual": "Казуальная",
    "family": "Семейная",
    "board-games": "Настольные",
    "card": "Карточная",
    "massively-multiplayer": "ММО",
    "sports": "Спорт",
    "horror": "Хоррор",
    "survival": "Выживание",
    "stealth": "Стелс",
    "open-world": "Открытый мир",
    "open world": "Открытый мир",
    "story-rich": "Сюжетная",
    "story rich": "Сюжетная",
    "sci-fi": "Sci-Fi",
    "science fiction": "Sci-Fi",
    "cyberpunk": "Киберпанк",
    "fantasy": "Фэнтези",
    "hack and slash": "Слэшер",
    "psychological horror": "Психологический хоррор",
    "roguelike": "Рогалик",
    "souls-like": "Соулслайк",
    "metroidvania": "Метроидвания",
    "mystery": "Детектив"
}

def translate_genres(raw_genres_list: Optional[List[str]]) -> str:
    """Translates and normalizes genres to Russian"""
    if not raw_genres_list:
        return "Экшен"
    result = []
    for g in raw_genres_list:
        if not g or not isinstance(g, str):
            continue
        g_clean = g.strip()
        g_lower = g_clean.lower()
        translated = GENRE_TRANSLATION_MAP.get(g_lower)
        if not translated:
            for k, v in GENRE_TRANSLATION_MAP.items():
                if k in g_lower:
                    translated = v
                    break
        chosen = translated if translated else g_clean
        if chosen not in result:
            result.append(chosen)
    return ", ".join(result) if result else "Экшен"

def get_rawg_key() -> str:
    return get_setting("rawg_api_key", "").strip()

def search_games(query: str, page_size: int = 15) -> Dict[str, Any]:
    api_key = get_rawg_key()
    if not api_key:
        return {
            "success": False,
            "requires_api_key": True,
            "message": "RAWG API Key не указан в Настройках. Укажите ключ для живого поиска по базе 500,000+ игр.",
            "results": get_sample_rawg_search(query)
        }
        
    try:
        url = f"{RAWG_BASE_URL}/games"
        params = {
            "key": api_key,
            "search": query,
            "page_size": page_size,
            "search_precise": True
        }
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            raw_results = data.get("results") or []
            formatted_results = []
            for item in raw_results:
                if isinstance(item, dict):
                    formatted_results.append(format_rawg_game_summary(item))
            return {
                "success": True,
                "count": data.get("count", len(formatted_results)),
                "results": formatted_results
            }
        elif response.status_code in [401, 403]:
            return {
                "success": False,
                "error": "Неверный или недействительный RAWG API Key.",
                "results": get_sample_rawg_search(query)
            }
        else:
            return {
                "success": False,
                "error": f"Ошибка RAWG API (HTTP {response.status_code})",
                "results": get_sample_rawg_search(query)
            }
    except Exception as e:
        logger.error(f"Error searching RAWG: {e}")
        return {
            "success": False,
            "error": f"Ошибка сети при запросе к RAWG: {str(e)}",
            "results": get_sample_rawg_search(query)
        }

def get_game_details(game_id_or_slug: str) -> Dict[str, Any]:
    api_key = get_rawg_key()
    if not api_key:
        return {
            "success": False,
            "requires_api_key": True,
            "message": "RAWG API Key не указан в Настройках."
        }
        
    try:
        url = f"{RAWG_BASE_URL}/games/{game_id_or_slug}"
        params = {"key": api_key}
        response = requests.get(url, params=params, timeout=10)
        
        if response.status_code == 200:
            item = response.json()
            formatted = format_rawg_game_details(item)
            return {"success": True, "game": formatted}
        else:
            return {
                "success": False,
                "error": f"Не удалось получить данные об игре (HTTP {response.status_code})"
            }
    except Exception as e:
        logger.error(f"Error fetching game details from RAWG: {e}")
        return {"success": False, "error": str(e)}

def find_existing_game_for_rawg(rawg_id: Optional[int], title: str = "", slug: str = "") -> Optional[Dict[str, Any]]:
    """
    Duplicate protection for 1-click adds (RAWG tool + Release Calendar):
    matches an existing library game by RAWG id first, then by normalized title / slug.
    """
    from database import get_games
    all_games = get_games()
    norm_title = (title or "").strip().lower()
    norm_slug = (slug or "").strip().lower()
    for g in all_games:
        if rawg_id and g.get("rawg_id") and int(g["rawg_id"]) == int(rawg_id):
            return g
        if norm_slug and (g.get("slug") or "").strip().lower() == norm_slug:
            return g
        if norm_title and (g.get("title") or "").strip().lower() == norm_title:
            return g
    return None


def quick_add_game(rawg_id: Optional[int], target_status: str = "backlog", game_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    details = None
    if rawg_id:
        det_res = get_game_details(str(rawg_id))
        if det_res.get("success") and det_res.get("game"):
            details = det_res.get("game")

    if not details and game_data:
        details = game_data

    if not details:
        return {"success": False, "error": "Не удалось получить метаданные игры для добавления."}

    # --- Duplicate protection: never create a second record for the same RAWG game ---
    probe_title = details.get("title") or (game_data or {}).get("title") or ""
    probe_slug = details.get("slug") or (game_data or {}).get("slug") or ""
    existing = find_existing_game_for_rawg(rawg_id or (game_data or {}).get("rawg_id"),
                                           title=probe_title, slug=probe_slug)
    if existing:
        updates = {}
        if rawg_id and not existing.get("rawg_id"):
            updates["rawg_id"] = rawg_id
        if not existing.get("cover_url") and details.get("cover_url"):
            updates["cover_url"] = details.get("cover_url")
            updates["background_url"] = details.get("background_url") or details.get("cover_url")
        if updates:
            from database import update_game
            updated = update_game(existing["id"], updates) or existing
        else:
            updated = existing
        return {
            "success": True,
            "duplicate": True,
            "game": updated,
            "message": f"«{updated.get('title')}» уже есть в библиотеке (статус: {updated.get('status')})."
        }

    title_for_hltb = details.get("title") or details.get("name") or "Новая игра"
    hltb_time = get_hltb_playtime(title_for_hltb)
    playtime_main = hltb_time

    # We do not compute playtime_extra or playtime_completionist here anymore
    playtime_extra = 0.0
    playtime_completionist = 0.0

    priority = "high" if target_status == "playing" else "medium"

    # Normalize genres to Russian
    raw_genres = details.get("genres", "")
    if isinstance(raw_genres, list):
        genres_str = translate_genres(raw_genres)
    elif isinstance(raw_genres, str) and raw_genres:
        genres_str = translate_genres([g.strip() for g in raw_genres.split(',')])
    else:
        genres_str = "Экшен"

    target_plat = details.get("platform") or "PC"

    new_game_data = {
        "title": details.get("title") or details.get("name") or "Новая игра",
        "slug": details.get("slug", ""),
        "rawg_id": details.get("rawg_id") or rawg_id,
        "cover_url": details.get("cover_url") or details.get("background_image") or "",
        "background_url": details.get("background_url") or details.get("background_image") or "",
        "status": target_status,
        "platform": target_plat,
        "platforms_list": details.get("platforms_list") or [target_plat],
        "genres": genres_str,
        "release_date": (details.get("platform_release_dates", {}).get(target_plat) or details.get("release_date") or details.get("released") or ""),
        "developer": details.get("developer") or "",
        "publisher": details.get("publisher") or "",
        "rawg_rating": float(details.get("rawg_rating") or details.get("rating") or 0.0),
        "metacritic": int(details.get("metacritic") or 0),
        "playtime_main": playtime_main,
        "playtime_source": "hltb" if playtime_main and playtime_main > 0 else "legacy",
        "playtime_extra": playtime_extra,
        "playtime_completionist": playtime_completionist,
        "user_playtime_minutes": 0,
        "rating_grade": "",
        "priority": priority,
        "notes": f"Добавлено через RAWG.io ({datetime_now_note()})"
    }

    created = create_game(new_game_data)
    return {"success": True, "game": created}

def datetime_now_note() -> str:
    from datetime import datetime
    return datetime.now().strftime("%d.%m.%Y")

def format_rawg_game_summary(item: Dict[str, Any]) -> Dict[str, Any]:
    # Safe handling if genres, tags, or platforms are None in API response
    genres_items = item.get("genres") or []
    raw_genres = [g.get("name") for g in genres_items if isinstance(g, dict) and g.get("name")]
    
    # Also check tags for rich genres like "Story Rich", "Sci-Fi", "Horror", "Open World"
    tags_items = item.get("tags") or []
    tags = [t.get("name") for t in tags_items if isinstance(t, dict) and t.get("name")]
    for t in tags[:10]:
        t_low = t.lower()
        if any(w in t_low for w in ["story rich", "horror", "stealth", "survival", "open world", "sci-fi", "cyberpunk", "souls", "roguelike"]):
            if t not in raw_genres:
                raw_genres.append(t)

    russian_genres = translate_genres(raw_genres)

    platforms_items = item.get("platforms") or []
    platforms = [
        p.get("platform", {}).get("name") 
        for p in platforms_items 
        if isinstance(p, dict) and isinstance(p.get("platform"), dict) and p.get("platform", {}).get("name")
    ]
    
    # We no longer calculate playtime from RAWG since we will fetch it from HLTB
    # Setting it to 0 / None so frontend knows it's empty
    playtime_main = 0.0
    playtime_extra = 0.0
    playtime_completionist = 0.0

    primary_platform = "PC"
    if platforms:
        if "PC" in platforms:
            primary_platform = "PC"
        elif "PlayStation 5" in platforms:
            primary_platform = "PlayStation 5"
        elif "Nintendo Switch" in platforms:
            primary_platform = "Nintendo Switch"
        else:
            primary_platform = platforms[0]

    # Map platform-specific release dates
    platform_release_dates = {}
    for p in platforms_items:
        if isinstance(p, dict):
            p_name = p.get("platform", {}).get("name")
            p_rel = p.get("released_at")
            if p_name and p_rel:
                platform_release_dates[p_name] = p_rel

    return {
        "rawg_id": item.get("id"),
        "title": item.get("name", "Unknown Title"),
        "slug": item.get("slug", ""),
        "cover_url": item.get("background_image") or "",
        "background_url": item.get("background_image") or "",
        "release_date": item.get("released") or "",
        "platform_release_dates": platform_release_dates,
        "rawg_rating": float(item.get("rating") or 0.0),
        "metacritic": int(item.get("metacritic") or 0),
        "genres": russian_genres,
        "platforms_list": platforms if platforms else ["PC"],
        "platform": primary_platform,
        "playtime_main": playtime_main,
        "playtime_extra": playtime_extra,
        "playtime_completionist": playtime_completionist
    }

def format_rawg_game_details(item: Dict[str, Any]) -> Dict[str, Any]:
    summary = format_rawg_game_summary(item)
    
    devs_items = item.get("developers") or []
    devs = [d.get("name") for d in devs_items if isinstance(d, dict) and d.get("name")]
    
    pubs_items = item.get("publishers") or []
    pubs = [p.get("name") for p in pubs_items if isinstance(p, dict) and p.get("name")]
    
    summary["developer"] = ", ".join(devs) if devs else ""
    summary["publisher"] = ", ".join(pubs) if pubs else ""
    summary["description"] = item.get("description_raw") or item.get("description") or ""
    summary["website"] = item.get("website") or ""
    
    return summary

def get_sample_rawg_search(query: str) -> List[Dict[str, Any]]:
    samples = [
        {
            "rawg_id": 974712,
            "title": "The Last of Us Part II Remastered",
            "slug": "the-last-of-us-part-ii-remastered",
            "cover_url": "https://media.rawg.io/media/games/043/043c7b2829286d9a5b3f11ab7284f67c.jpg",
            "background_url": "https://media.rawg.io/media/screenshots/6bf/6bfdc1b67e3a985f4eefee5f2fcb6c08.jpg",
            "release_date": "2024-01-19",
            "rawg_rating": 4.5,
            "metacritic": 90,
            "genres": "Экшен, Приключения, Сюжетная",
            "platforms_list": ["PC", "PlayStation 5"],
            "platform": "PC",
            "playtime_main": 0.0,
            "playtime_extra": 0.0,
            "playtime_completionist": 0.0

        },
        {
            "rawg_id": 401664,
            "title": "Senua's Saga: Hellblade II",
            "slug": "senuas-saga-hellblade-ii",
            "cover_url": "https://media.rawg.io/media/games/606/606990ae0ea5ee5d9d71c77f0a8276f5.jpg",
            "background_url": "https://media.rawg.io/media/screenshots/003/0037a54911cb3a890471bdf483b8a1c9.jpg",
            "release_date": "2024-05-21",
            "rawg_rating": 4.2,
            "metacritic": 81,
            "genres": "Экшен, Приключения, Психологический хоррор",
            "platforms_list": ["PC", "Xbox Series S/X"],
            "platform": "PC",
            "playtime_main": 0.0,
            "playtime_extra": 0.0,
            "playtime_completionist": 0.0

        },
        {
            "rawg_id": 892556,
            "title": "Death Stranding 2: On the Beach",
            "slug": "death-stranding-2-on-the-beach",
            "cover_url": "https://media.rawg.io/media/games/8ef/8ef309ee2e74da00f7e44b8ee78e8749.jpg",
            "background_url": "https://media.rawg.io/media/screenshots/c58/c589d98342898dbfce551ad36e846067.jpg",
            "release_date": "2025-11-01",
            "rawg_rating": 4.8,
            "metacritic": 0,
            "genres": "Sci-Fi, Приключения, Открытый мир",
            "platforms_list": ["PC", "PlayStation 5"],
            "platform": "PC",
            "playtime_main": 0.0,
            "playtime_extra": 0.0,
            "playtime_completionist": 0.0

        },
        {
            "rawg_id": 612803,
            "title": "Ghost of Tsushima DIRECTOR'S CUT",
            "slug": "ghost-of-tsushima-directors-cut",
            "cover_url": "https://media.rawg.io/media/games/505/5050f244192b0c3674d8124fa48db069.jpg",
            "background_url": "https://media.rawg.io/media/screenshots/5c7/5c7a52fce63b7ce2bca6ca50444dbef6.jpg",
            "release_date": "2024-05-16",
            "rawg_rating": 4.6,
            "metacritic": 88,
            "genres": "Экшен, Приключения, Открытый мир",
            "platforms_list": ["PC", "PlayStation 5"],
            "platform": "PC",
            "playtime_main": 0.0,
            "playtime_extra": 0.0,
            "playtime_completionist": 0.0

        },
        {
            "rawg_id": 870420,
            "title": "Silent Hill 2 Remake",
            "slug": "silent-hill-2-remake",
            "cover_url": "https://media.rawg.io/media/games/0df/0df1c998f4bbd0f8a8bb61501c64ebff.jpg",
            "background_url": "https://media.rawg.io/media/screenshots/316/3167b57b9c9fec719e71ec93e7f6dc74.jpg",
            "release_date": "2024-10-08",
            "rawg_rating": 4.4,
            "metacritic": 86,
            "genres": "Хоррор, Выживание, Детектив",
            "platforms_list": ["PC", "PlayStation 5"],
            "platform": "PC",
            "playtime_main": 0.0,
            "playtime_extra": 0.0,
            "playtime_completionist": 0.0

        }
    ]
    if query:
        q_lower = query.lower()
        matched = [s for s in samples if q_lower in s["title"].lower() or q_lower in s["genres"].lower()]
        return matched if matched else samples
    return samples


# --- BULK METADATA & COVER ENRICHER ---

def enrich_single_game(game_id: int) -> Dict[str, Any]:
    """
    Search RAWG for the game by its title and update cover art, genres,
    release date, playtime, and developer metadata.
    """
    from database import get_game_by_id, update_game
    
    game = get_game_by_id(game_id)
    if not game:
        return {"success": False, "error": "Игра не найдена в базе данных."}

    api_key = get_rawg_key()
    if not api_key:
        return {
            "success": False,
            "requires_api_key": True,
            "message": "RAWG API Key не указан в Настройках. Укажите ключ в разделе «Настройки API» для авто-загрузки обложек."
        }

    title = game.get("title", "").strip()
    if not title:
        return {"success": False, "error": "Название игры пустое."}

    # Clean title from edition noise for better search match
    search_q = title
    for noise in ["(All DLC)", "+ DLC", "plus DLC", "Definitive Edition", "Remastered", "Edition"]:
        search_q = search_q.replace(noise, "").strip()

    search_res = search_games(search_q, page_size=5)
    if not search_res.get("success") or not search_res.get("results"):
        return {"success": False, "error": f"В RAWG не найдено совпадений по «{search_q}»."}

    results = search_res.get("results", [])
    # Find exact or best match
    best_item = results[0]
    title_lower = title.lower()
    for r in results:
        if r.get("title", "").lower() == title_lower or r.get("slug", "") == title_lower:
            best_item = r
            break

    # Fetch full details
    details = None
    if best_item.get("rawg_id"):
        det_res = get_game_details(str(best_item["rawg_id"]))
        if det_res.get("success") and det_res.get("game"):
            details = det_res["game"]

    if not details:
        details = best_item

    # Determine platform-appropriate release date
    platform_name = game.get("platform", "")
    plat_dates = details.get("platform_release_dates") or best_item.get("platform_release_dates") or {}
    matched_plat_date = None
    for p_key, p_val in plat_dates.items():
        if platform_name and platform_name.lower() in p_key.lower():
            matched_plat_date = p_val
            break

    final_release_date = matched_plat_date or details.get("release_date") or details.get("released") or game.get("release_date") or ""

    updates = {
        "rawg_id": details.get("rawg_id") or best_item.get("rawg_id"),
        "slug": details.get("slug") or best_item.get("slug", ""),
        "cover_url": details.get("cover_url") or details.get("background_image") or "",
        "background_url": details.get("background_url") or details.get("background_image") or "",
        "genres": details.get("genres") or best_item.get("genres") or game.get("genres") or "Экшен",
        "release_date": final_release_date,
        "developer": details.get("developer") or game.get("developer") or "",
        "publisher": details.get("publisher") or game.get("publisher") or "",
        "rawg_rating": float(details.get("rawg_rating") or details.get("rating") or game.get("rawg_rating") or 0.0),
        "metacritic": int(details.get("metacritic") or game.get("metacritic") or 0)
    }

    # Only update playtime if previously unset or default
    if not game.get("playtime_main") or game.get("playtime_main") <= 0 or game.get("playtime_main") == 10.0:
        game_title = details.get("title") or best_item.get("title") or game.get("title", "")
        hltb_time = get_hltb_playtime(game_title)
        if hltb_time is not None and hltb_time > 0:
            updates["playtime_main"] = hltb_time
            updates["playtime_source"] = "hltb"

    updated_game = update_game(game_id, updates)
    return {
        "success": True,
        "game": updated_game,
        "matched_title": details.get("title") or best_item.get("title")
    }

def bulk_enrich_missing_games(status: Optional[str] = None, batch_size: int = 25) -> Dict[str, Any]:
    """
    Finds games without cover_url and enriches up to batch_size games in one go.
    """
    from database import get_games
    
    api_key = get_rawg_key()
    if not api_key:
        return {
            "success": False,
            "requires_api_key": True,
            "message": "RAWG API Key не указан в Настройках. Укажите ключ в разделе «Настройки API»."
        }

    all_games = get_games(status=status)
    missing_games = [g for g in all_games if not g.get("cover_url") or g.get("cover_url").strip() == ""]
    
    target_batch = missing_games[:batch_size]
    
    enriched_count = 0
    errors = []
    
    for g in target_batch:
        res = enrich_single_game(g["id"])
        if res.get("success"):
            enriched_count += 1
        else:
            errors.append(f"{g.get('title')}: {res.get('error') or res.get('message')}")
            
    remaining_count = len(missing_games) - len(target_batch)
    
    return {
        "success": True,
        "enriched_count": enriched_count,
        "processed_count": len(target_batch),
        "total_missing": len(missing_games),
        "remaining_count": max(0, remaining_count),
        "has_more": remaining_count > 0,
        "errors": errors
    }


# ============================================================================
# RELEASE CALENDAR (Календарь релизов) — RAWG dates endpoint integration
# ============================================================================

CALENDAR_PLATFORM_FAMILIES = {
    "pc": ["PC"],
    "playstation": ["PlayStation 5", "PlayStation 4", "Sony Entertainment Console",
                    "PlayStation 3", "PlayStation VR2", "PSVR"],
    "xbox": ["Xbox Series S/X", "Xbox One", "Xbox 360", "Xbox Cloud Gaming"],
    "nintendo": ["Nintendo Switch", "Nintendo Switch 2", "Nintendo", "Game Boy",
                 "NES", "SNES", "Nintendo 3DS", "Nintendo DS", "WiiU", "Wii"],
}

_RAWG_PLATFORM_ID_FAMILIES = {
    1: "pc", 4: "pc",                                    # PC, Software (TBD)
    18: "playstation", 9: "playstation", 7: "playstation",
    16: "playstation", 15: "playstation", 19: "playstation",
    14: "xbox", 80: "xbox", 12: "xbox", 3: "xbox", 28: "xbox",
    13: "nintendo", 6: "nintendo", 5: "nintendo", 43: "nintendo",
    94: "nintendo", 48: "nintendo", 46: "nintendo", 26: "nintendo",
    49: "nintendo", 51: "nintendo", 53: "nintendo",
}

_calendar_cache: Dict[str, Any] = {"key": None, "ts": 0.0}
CALENDAR_CACHE_TTL_SECONDS = 6 * 3600  # calendar month data is static; cache 6h

def _get_rawg_key_preferred() -> str:
    """Settings DB key first (existing architecture), env fallback for fresh installs."""
    key = get_rawg_key()
    if not key:
        key = os.environ.get("RAWG_API_KEY", "").strip()
    return key


def get_platform_family_for_name(name: Optional[str]) -> List[str]:
    """Maps a RAWG platform name to one of the calendar families: pc/playstation/xbox/nintendo."""
    if not name:
        return []
    p = name.strip().lower()
    if p in ("pc", "software (tbd)"):
        return ["pc"]
    if any(t in p for t in ["playstation", "ps5", "ps4", "ps3", "sony entertainment console", "psvr"]):
        return ["playstation"]
    if "xbox" in p:
        return ["xbox"]
    if any(t in p for t in ["nintendo", "switch", "game boy", "nes", "snes", "wii", "3ds", "ds"]):
        return ["nintendo"]
    return []


def _format_release_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Normalizes a RAWG date-list game entry into a compact calendar card payload."""
    genres_items = item.get("genres") or []
    raw_genres = [g.get("name") for g in genres_items if isinstance(g, dict) and g.get("name")]
    tags_items = item.get("tags") or []
    for t in tags_items:
        if isinstance(t, dict) and t.get("name"):
            t_low = t["name"].lower()
            if any(w in t_low for w in ["story rich", "horror", "stealth", "survival",
                                        "open world", "sci-fi", "cyberpunk", "souls",
                                        "roguelike", "metroidvania"]) and t["name"] not in raw_genres:
                raw_genres.append(t["name"])

    platforms_items = item.get("platforms") or []
    platforms_list: List[str] = []
    families: List[str] = []
    for p in platforms_items:
        if not isinstance(p, dict):
            continue
        pdata = p.get("platform") or {}
        pid = pdata.get("id")
        pname = pdata.get("name") or ""
        fams = get_platform_family_for_name(pname)
        if not fams and pid in _RAWG_PLATFORM_ID_FAMILIES:
            fams = [_RAWG_PLATFORM_ID_FAMILIES[pid]]
        for f in fams:
            if f not in families:
                families.append(f)
        if pname and pname not in platforms_list:
            platforms_list.append(pname)

    primary_platform = "PC"
    for pref in ["PC", "PlayStation 5", "Xbox Series S/X", "Nintendo Switch"]:
        if pref in platforms_list:
            primary_platform = pref
            break
    else:
        if platforms_list:
            primary_platform = platforms_list[0]

    added_by_status = item.get("added_by_status") or {}
    added_by_user = (added_by_status.get("by") or {}).get("username") or ""

    stores_items = item.get("stores") or []
    store_urls = [s.get("store", {}).get("url") for s in stores_items
                  if isinstance(s, dict) and isinstance(s.get("store"), dict) and s.get("store", {}).get("url")]

    return {
        "rawg_id": item.get("id"),
        "title": item.get("name", "Unknown Title"),
        "slug": item.get("slug", ""),
        "cover_url": item.get("background_image") or "",
        "background_url": item.get("background_image") or "",
        "release_date": item.get("released") or "",
        "tba": bool(item.get("tba")),
        "rawg_rating": float(item.get("rating") or 0.0),
        "metacritic": int(item.get("metacritic") or 0),
        "genres": translate_genres(raw_genres) if raw_genres else "",
        "platforms_list": platforms_list if platforms_list else ["PC"],
        "platform_families": families,
        "platform": primary_platform,
        "added_by": added_by_user,
        "store_url": store_urls[0] if store_urls else "",
    }


def get_releases_calendar(year: int, month: int) -> Dict[str, Any]:
    """
    Fetches all game releases for a given month from RAWG `/games` with
    `dates` filter (same client, same key, same error-handling style).
    Results are deduplicated by RAWG id and cached server-side.
    """
    api_key = _get_rawg_key_preferred()
    if not api_key:
        return {
            "success": False,
            "requires_api_key": True,
            "message": "RAWG API Key не настроен. Укажите ключ в разделе «Настройки API» для работы календаря релизов.",
            "results": []
        }

    try:
        year = int(year)
        month = int(month)
    except (TypeError, ValueError):
        return {"success": False, "error": "Некорректный формат месяца. Ожидается ГГГГ-ММ.", "results": []}
    if year < 1970 or month < 1 or month > 12:
        return {"success": False, "error": "Недопустимое значение года или месяца.", "results": []}

    cache_key = f"{year}-{month:02d}"
    now_ts = time.time()
    if _calendar_cache.get("key") == cache_key and (now_ts - _calendar_cache.get("ts", 0)) < CALENDAR_CACHE_TTL_SECONDS:
        return {"success": True, "cached": True, "year": year, "month": month,
                "count": len(_calendar_cache["results"]), "results": _calendar_cache["results"]}

    last_day = 31
    while True:  # clamp end day for months with fewer days
        try:
            datetime(year, month, last_day)
            break
        except ValueError:
            last_day -= 1

    start_iso = f"{year}-{month:02d}-01"
    end_iso = f"{year}-{month:02d}-{last_day:02d}"

    results: List[Dict[str, Any]] = []
    seen_ids = set()
    page = 1
    max_pages = 6  # up to ~360 releases per month (page_size 60)
    errors_seen = []

    try:
        while page <= max_pages:
            url = f"{RAWG_BASE_URL}/games"
            params = {
                "key": api_key,
                "ordering": "release_date",
                "dates": f"{start_iso},{end_iso}",
                "page": page,
                "page_size": 60,
                "no_screenshots": "",
                "no_games": "",
            }
            response = requests.get(url, params=params, timeout=15)
            if response.status_code in (401, 403):
                return {"success": False, "error": "Неверный или недействительный RAWG API Key.", "results": []}
            if response.status_code != 200:
                err = f"Ошибка RAWG API (HTTP {response.status_code})"
                if page == 1:
                    return {"success": False, "error": err, "results": []}
                errors_seen.append(err)
                break
            data = response.json()
            raw_results = data.get("results") or []
            for item in raw_results:
                if not isinstance(item, dict):
                    continue
                rid = item.get("id")
                if rid in seen_ids:
                    continue
                seen_ids.add(rid)
                results.append(_format_release_item(item))
            next_url = data.get("next")
            if not next_url or not raw_results:
                break
            page += 1
    except Exception as e:
        logger.error(f"Error fetching RAWG release calendar: {e}")
        if page == 1:
            return {"success": False, "error": f"Ошибка сети при запросе к RAWG: {str(e)}", "results": []}

    results.sort(key=lambda r: (r.get("release_date") or "9999-12-31", -(r.get("rawg_rating") or 0)))

    _calendar_cache["key"] = cache_key
    _calendar_cache["ts"] = now_ts
    _calendar_cache["results"] = results

    return {
        "success": True,
        "cached": False,
        "year": year,
        "month": month,
        "range": {"start": start_iso, "end": end_iso},
        "count": len(results),
        "results": results,
        "partial_error": errors_seen[0] if errors_seen else None,
    }


def get_game_movies(rawg_id: int) -> Dict[str, Any]:
    """
    RAWG `/games/{id}/movies` endpoint — optional supplementary trailer source.
    Returns normalized [{name, video_id, embed_url, watch_url}] list so the frontend
    can reuse the existing single trailer modal / iframe player.
    """
    api_key = _get_rawg_key_preferred()
    if not api_key:
        return {"success": False, "requires_api_key": True, "message": "RAWG API Key не настроен.", "movies": []}
    try:
        url = f"{RAWG_BASE_URL}/games/{rawg_id}/movies"
        response = requests.get(url, params={"key": api_key}, timeout=10)
        if response.status_code != 200:
            return {"success": False, "error": f"Ошибка RAWG API (HTTP {response.status_code})", "movies": []}
        movies = []
        for m in (response.json().get("results") or []):
            if not isinstance(m, dict):
                continue
            data = m.get("data") or {}
            video_id = data.get("480") or data.get("max") or data.get("720") or ""
            if not video_id:
                continue
            movies.append({
                "name": m.get("name") or "Трейлер",
                "video_id": video_id,
                "embed_url": f"https://www.youtube.com/embed/{video_id}?autoplay=1&rel=0",
                "watch_url": f"https://www.youtube.com/watch?v={video_id}",
            })
        return {"success": True, "movies": movies}
    except Exception as e:
        logger.error(f"Error fetching RAWG movies for {rawg_id}: {e}")
        return {"success": False, "error": str(e), "movies": []}
