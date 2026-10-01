"""
RAWG.io API Integration Service
Provides instant game search, automated metadata auto-fetch, cover arts,
Russian genre translation, and playtime estimation for seamless 1-click backlog additions.
"""
import requests
import logging
from typing import Dict, Any, List, Optional
from database import get_setting, create_game

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

    playtime_main = float(details.get("playtime_main") or details.get("playtime") or 10.0)
    if playtime_main <= 0:
        playtime_main = 10.0

    playtime_extra = float(details.get("playtime_extra") or round(playtime_main * 1.35, 1))
    playtime_completionist = float(details.get("playtime_completionist") or round(playtime_main * 1.8, 1))

    priority = "high" if target_status == "playing" else "medium"

    # Normalize genres to Russian
    raw_genres = details.get("genres", "")
    if isinstance(raw_genres, list):
        genres_str = translate_genres(raw_genres)
    elif isinstance(raw_genres, str) and raw_genres:
        genres_str = translate_genres([g.strip() for g in raw_genres.split(',')])
    else:
        genres_str = "Экшен"

    new_game_data = {
        "title": details.get("title") or details.get("name") or "Новая игра",
        "slug": details.get("slug", ""),
        "rawg_id": details.get("rawg_id") or rawg_id,
        "cover_url": details.get("cover_url") or details.get("background_image") or "",
        "background_url": details.get("background_url") or details.get("background_image") or "",
        "status": target_status,
        "platform": details.get("platform") or "PC",
        "platforms_list": details.get("platforms_list") or ["PC"],
        "genres": genres_str,
        "release_date": details.get("release_date") or details.get("released") or "",
        "developer": details.get("developer") or "",
        "publisher": details.get("publisher") or "",
        "rawg_rating": float(details.get("rawg_rating") or details.get("rating") or 0.0),
        "metacritic": int(details.get("metacritic") or 0),
        "playtime_main": playtime_main,
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
    
    raw_playtime = item.get("playtime") or 0
    playtime_main = float(raw_playtime) if raw_playtime > 0 else 10.0
    playtime_extra = round(playtime_main * 1.35, 1)
    playtime_completionist = round(playtime_main * 1.8, 1)

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

    return {
        "rawg_id": item.get("id"),
        "title": item.get("name", "Unknown Title"),
        "slug": item.get("slug", ""),
        "cover_url": item.get("background_image") or "",
        "background_url": item.get("background_image") or "",
        "release_date": item.get("released") or "",
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
            "playtime_main": 24.0,
            "playtime_extra": 31.0,
            "playtime_completionist": 42.0
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
            "playtime_main": 7.5,
            "playtime_extra": 9.0,
            "playtime_completionist": 11.0
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
            "playtime_main": 35.0,
            "playtime_extra": 55.0,
            "playtime_completionist": 85.0
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
            "playtime_main": 25.0,
            "playtime_extra": 44.0,
            "playtime_completionist": 62.0
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
            "playtime_main": 15.0,
            "playtime_extra": 18.0,
            "playtime_completionist": 22.0
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

    updates = {
        "rawg_id": details.get("rawg_id") or best_item.get("rawg_id"),
        "slug": details.get("slug") or best_item.get("slug", ""),
        "cover_url": details.get("cover_url") or details.get("background_image") or "",
        "background_url": details.get("background_url") or details.get("background_image") or "",
        "genres": details.get("genres") or best_item.get("genres") or game.get("genres") or "Экшен",
        "release_date": details.get("release_date") or details.get("released") or game.get("release_date") or "",
        "developer": details.get("developer") or game.get("developer") or "",
        "publisher": details.get("publisher") or game.get("publisher") or "",
        "rawg_rating": float(details.get("rawg_rating") or details.get("rating") or game.get("rawg_rating") or 0.0),
        "metacritic": int(details.get("metacritic") or game.get("metacritic") or 0)
    }

    # Only update playtime if previously unset or default
    if not game.get("playtime_main") or game.get("playtime_main") <= 0 or game.get("playtime_main") == 10.0:
        p_main = float(details.get("playtime_main") or details.get("playtime") or 10.0)
        if p_main > 0:
            updates["playtime_main"] = p_main
            updates["playtime_extra"] = round(p_main * 1.35, 1)
            updates["playtime_completionist"] = round(p_main * 1.8, 1)

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
