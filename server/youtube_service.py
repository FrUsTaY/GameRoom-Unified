"""
YouTube Data API v3 Service for GAME-ROOM's Backlog Tracker
Fetches official trailers, gameplay footage, launch previews, and reviews
with caching, metadata formatting, and graceful fallback when API key is unconfigured.
"""
import requests
import html
import logging
import urllib.parse
from typing import Dict, Any, List, Optional
from database import get_setting

logger = logging.getLogger("youtube_service")
YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3/search"

# In-memory LRU cache for queries
_cache: Dict[str, Dict[str, Any]] = {}

# Curated high-quality video links for sample/seeded games
CURATED_TRAILERS: Dict[str, Dict[str, Any]] = {
    "the last of us part ii": {
        "channelTitle": "PlayStation",
        "thumbnail_url": "https://i.ytimg.com/vi/qPNiIeKMHyg/hqdefault.jpg",
        "trailer": {
            "videoId": "qPNiIeKMHyg",
            "title": "The Last of Us Part II Remastered - Announce Trailer | PS5 Games"
        },
        "gameplay": {
            "videoId": "vhII1qlcZ4o",
            "title": "The Last of Us Part II - Official Extended Gameplay"
        },
        "launch": {
            "videoId": "TXl9GI1p_Os",
            "title": "The Last of Us Part II - Official Launch Trailer | PS4"
        },
        "review": {
            "videoId": "gJ-v7xPz44k",
            "title": "The Last of Us Part II: Обзор от StopGame"
        }
    },
    "senua's saga: hellblade ii": {
        "channelTitle": "Xbox",
        "thumbnail_url": "https://i.ytimg.com/vi/wWzK5mE0x1Q/hqdefault.jpg",
        "trailer": {
            "videoId": "wWzK5mE0x1Q",
            "title": "Senua's Saga: Hellblade II | Official Announce Trailer"
        },
        "gameplay": {
            "videoId": "3Y9f59iY7Wk",
            "title": "Senua's Saga: Hellblade II - Official Gameplay Showcase"
        },
        "launch": {
            "videoId": "1xK79M3Zg88",
            "title": "Senua's Saga: Hellblade II | Official Launch Trailer"
        },
        "review": {
            "videoId": "i23XgV6hW6w",
            "title": "Senua's Saga: Hellblade II: Видеообзор от StopGame"
        }
    },
    "ghost of tsushima": {
        "channelTitle": "PlayStation",
        "thumbnail_url": "https://i.ytimg.com/vi/vtY0vQ4V154/hqdefault.jpg",
        "trailer": {
            "videoId": "vtY0vQ4V154",
            "title": "Ghost of Tsushima Director's Cut - PC Features Trailer"
        },
        "gameplay": {
            "videoId": "0s_nF_n_w6E",
            "title": "Ghost of Tsushima - 18 Minutes of In-Depth Gameplay"
        },
        "launch": {
            "videoId": "iqysmXQ_i6A",
            "title": "Ghost of Tsushima - Launch Trailer | PS4"
        },
        "review": {
            "videoId": "c716N6-w_kU",
            "title": "Ghost of Tsushima: Обзор от StopGame"
        }
    },
    "silent hill 2": {
        "channelTitle": "KONAMI",
        "thumbnail_url": "https://i.ytimg.com/vi/pyC_qiW_4ZY/hqdefault.jpg",
        "trailer": {
            "videoId": "pyC_qiW_4ZY",
            "title": "SILENT HILL 2 | Story Trailer (4K)"
        },
        "gameplay": {
            "videoId": "e4B8Y7W2_aA",
            "title": "SILENT HILL 2 - Official Gameplay Trailer"
        },
        "launch": {
            "videoId": "o4J5G4o6hWk",
            "title": "SILENT HILL 2 | Launch Trailer (4K)"
        },
        "review": {
            "videoId": "Fz5q6sV6w90",
            "title": "Silent Hill 2 Remake: Обзор от StopGame"
        }
    },
    "death stranding 2": {
        "channelTitle": "PlayStation",
        "thumbnail_url": "https://i.ytimg.com/vi/TrxrFvh9i4w/hqdefault.jpg",
        "trailer": {
            "videoId": "TrxrFvh9i4w",
            "title": "DEATH STRANDING 2: ON THE BEACH – State of Play Trailer | PS5 Games"
        },
        "gameplay": {
            "videoId": "TrxrFvh9i4w",
            "title": "DEATH STRANDING 2 - Official Gameplay & World Preview"
        },
        "launch": {
            "videoId": "TrxrFvh9i4w",
            "title": "DEATH STRANDING 2: ON THE BEACH - Special Trailer"
        },
        "review": {
            "videoId": "TrxrFvh9i4w",
            "title": "Death Stranding 2: Анализ и ожидания от StopGame"
        }
    },
    "planet of lana": {
        "channelTitle": "Thunderful Games",
        "thumbnail_url": "https://i.ytimg.com/vi/_T1J6f6s3sA/hqdefault.jpg",
        "trailer": {
            "videoId": "_T1J6f6s3sA",
            "title": "Planet of Lana - Official Cinematic Trailer"
        },
        "gameplay": {
            "videoId": "lZ91t8n2Xk8",
            "title": "Planet of Lana - Official Gameplay Trailer"
        },
        "launch": {
            "videoId": "sV8Gk3zZ7Yg",
            "title": "Planet of Lana - Official Launch Trailer"
        },
        "review": {
            "videoId": "X_8z8eW3oQ0",
            "title": "Planet of Lana: Обзор от StopGame"
        }
    },
    "cyberpunk 2077": {
        "channelTitle": "Cyberpunk 2077",
        "thumbnail_url": "https://i.ytimg.com/vi/kfSXoxvJd_4/hqdefault.jpg",
        "trailer": {
            "videoId": "kfSXoxvJd_4",
            "title": "Cyberpunk 2077: Phantom Liberty — Official Cinematic Trailer"
        },
        "gameplay": {
            "videoId": "7v9n4U7lZ44",
            "title": "Cyberpunk 2077: Phantom Liberty — Official Gameplay Breakdown"
        },
        "launch": {
            "videoId": "4Z8lK2m_e7A",
            "title": "Cyberpunk 2077: Phantom Liberty — Official Launch Trailer"
        },
        "review": {
            "videoId": "K8g9V7l5_bQ",
            "title": "Cyberpunk 2077: Phantom Liberty: Обзор от StopGame"
        }
    }
}

def get_youtube_key() -> str:
    """Retrieve YouTube API Key from database settings"""
    return get_setting("youtube_api_key", "").strip()

def search_youtube(query: str, max_results: int = 4, mode: str = "trailer") -> Dict[str, Any]:
    """
    Search YouTube videos using YouTube Data API v3 with caching and fallback.
    """
    cache_key = f"{query}_{max_results}".lower()
    if cache_key in _cache:
        return _cache[cache_key]

    api_key = get_youtube_key()
    
    # Check curated fallback match
    curated_match = None
    query_lower = query.lower()
    for k, v in CURATED_TRAILERS.items():
        if k in query_lower:
            curated_match = v
            break

    if not api_key:
        if curated_match:
            mode_data = curated_match.get(mode) or curated_match.get("trailer")
            vid_id = mode_data["videoId"]
            vid_title = mode_data["title"]
            
            result = {
                "success": True,
                "is_curated": True,
                "requires_api_key": False,
                "query": query,
                "mode": mode,
                "primary_video": {
                    "videoId": vid_id,
                    "title": vid_title,
                    "channelTitle": curated_match["channelTitle"],
                    "thumbnail_url": curated_match["thumbnail_url"],
                    "embed_url": f"https://www.youtube.com/embed/{vid_id}?autoplay=1&rel=0",
                    "watch_url": f"https://www.youtube.com/watch?v={vid_id}"
                },
                "videos": [
                    {
                        "videoId": vid_id,
                        "title": vid_title,
                        "channelTitle": curated_match["channelTitle"],
                        "thumbnail_url": curated_match["thumbnail_url"],
                        "embed_url": f"https://www.youtube.com/embed/{vid_id}?autoplay=1&rel=0",
                        "watch_url": f"https://www.youtube.com/watch?v={vid_id}"
                    }
                ],
                "fallback_search_url": f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}"
            }
            _cache[cache_key] = result
            return result

        # No key and not in curated list
        return {
            "success": False,
            "requires_api_key": True,
            "message": "YouTube API Key не указан в Настройках. Укажите ключ в разделе «Настройки API» для встроенного воспроизведения.",
            "query": query,
            "mode": mode,
            "fallback_search_url": f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}"
        }

    # Call YouTube Data API v3
    try:
        params = {
            "key": api_key,
            "part": "snippet",
            "q": query,
            "type": "video",
            "videoEmbeddable": "true",
            "maxResults": max_results,
            "safeSearch": "none"
        }
        resp = requests.get(YOUTUBE_API_URL, params=params, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("items", [])
            videos = []
            for item in items:
                vid_id = item.get("id", {}).get("videoId")
                if not vid_id:
                    continue
                snippet = item.get("snippet", {})
                thumbs = snippet.get("thumbnails", {})
                thumb_url = (
                    thumbs.get("high", {}).get("url") or 
                    thumbs.get("medium", {}).get("url") or 
                    thumbs.get("default", {}).get("url") or 
                    f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg"
                )
                
                v_title = html.unescape(snippet.get("title", "Game Video"))
                ch_title = html.unescape(snippet.get("channelTitle", "YouTube"))
                
                videos.append({
                    "videoId": vid_id,
                    "title": v_title,
                    "channelTitle": ch_title,
                    "description": html.unescape(snippet.get("description", "")),
                    "thumbnail_url": thumb_url,
                    "published_at": snippet.get("publishTime", ""),
                    "embed_url": f"https://www.youtube.com/embed/{vid_id}?autoplay=1&rel=0",
                    "watch_url": f"https://www.youtube.com/watch?v={vid_id}"
                })

            if videos:
                res = {
                    "success": True,
                    "requires_api_key": False,
                    "query": query,
                    "mode": mode,
                    "primary_video": videos[0],
                    "videos": videos,
                    "fallback_search_url": f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}"
                }
                _cache[cache_key] = res
                return res
            else:
                return {
                    "success": False,
                    "requires_api_key": False,
                    "error": f"По запросу «{query}» не найдено встраиваемых видео на YouTube.",
                    "query": query,
                    "mode": mode,
                    "fallback_search_url": f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}"
                }
        elif resp.status_code in [400, 403]:
            err_data = resp.json().get("error", {})
            err_msg = err_data.get("message", "Неверный ключ YouTube API или превышена квота запросов.")
            
            if curated_match:
                mode_data = curated_match.get(mode) or curated_match.get("trailer")
                vid_id = mode_data["videoId"]
                vid_title = mode_data["title"]
                return {
                    "success": True,
                    "is_curated": True,
                    "warning": f"YouTube API Error: {err_msg}. Использован резервный трейлер.",
                    "query": query,
                    "mode": mode,
                    "primary_video": {
                        "videoId": vid_id,
                        "title": vid_title,
                        "channelTitle": curated_match["channelTitle"],
                        "thumbnail_url": curated_match["thumbnail_url"],
                        "embed_url": f"https://www.youtube.com/embed/{vid_id}?autoplay=1&rel=0",
                        "watch_url": f"https://www.youtube.com/watch?v={vid_id}"
                    },
                    "videos": [
                        {
                            "videoId": vid_id,
                            "title": vid_title,
                            "channelTitle": curated_match["channelTitle"],
                            "thumbnail_url": curated_match["thumbnail_url"],
                            "embed_url": f"https://www.youtube.com/embed/{vid_id}?autoplay=1&rel=0",
                            "watch_url": f"https://www.youtube.com/watch?v={vid_id}"
                        }
                    ],
                    "fallback_search_url": f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}"
                }
            
            return {
                "success": False,
                "error": f"Ошибка YouTube API ({resp.status_code}): {err_msg}",
                "query": query,
                "mode": mode,
                "fallback_search_url": f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}"
            }
        else:
            return {
                "success": False,
                "error": f"Ошибка сервера YouTube (HTTP {resp.status_code})",
                "query": query,
                "mode": mode,
                "fallback_search_url": f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}"
            }
    except Exception as e:
        logger.error(f"Error fetching YouTube video: {e}")
        return {
            "success": False,
            "error": f"Сетевая ошибка при запросе к YouTube: {str(e)}",
            "query": query,
            "mode": mode,
            "fallback_search_url": f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(query)}"
        }

def get_game_video(
    title: str,
    platform: Optional[str] = None,
    mode: str = "trailer"
) -> Dict[str, Any]:
    """
    Get game trailer, gameplay, launch trailer, or review.
    """
    clean_title = title.strip()
    if mode == "gameplay":
        query = f"{clean_title} gameplay trailer"
    elif mode == "launch":
        query = f"{clean_title} launch trailer"
    elif mode == "review":
        query = f"{clean_title} обзор StopGame"
    else:
        query = f"{clean_title} official trailer"

    return search_youtube(query, max_results=4, mode=mode)
