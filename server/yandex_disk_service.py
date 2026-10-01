"""
Yandex.Disk Cloud Backup & Sync Service
Handles OAuth authorization, uploading database dumps, listing cloud backups,
and restoring game backlog data.
"""
import requests
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from database import (
    get_setting, export_full_database_json, 
    import_full_database_json
)

logger = logging.getLogger("yandex_disk_service")
YANDEX_API_BASE = "https://cloud-api.yandex.net/v1/disk"

def get_yandex_token() -> str:
    return get_setting("yandex_disk_token", "").strip()

def get_backup_folder() -> str:
    folder = get_setting("yandex_backup_folder", "disk:/GameBacklog_Backups").strip()
    if not folder.startswith("disk:") and not folder.startswith("app:"):
        folder = f"disk:/{folder.lstrip('/')}"
    return folder

def get_headers() -> Dict[str, str]:
    token = get_yandex_token()
    return {
        "Authorization": f"OAuth {token}",
        "Accept": "application/json"
    }

def check_yandex_status() -> Dict[str, Any]:
    token = get_yandex_token()
    if not token:
        return {
            "connected": False,
            "message": "OAuth-токен Яндекс.Диска не настроен."
        }
        
    try:
        response = requests.get(f"{YANDEX_API_BASE}/", headers=get_headers(), timeout=10)
        if response.status_code == 200:
            data = response.json()
            total_gb = round(data.get("total_space", 0) / (1024**3), 2)
            used_gb = round(data.get("used_space", 0) / (1024**3), 2)
            user = data.get("user", {}).get("display_name", "Yandex User")
            return {
                "connected": True,
                "user": user,
                "total_gb": total_gb,
                "used_gb": used_gb,
                "free_gb": round(total_gb - used_gb, 2),
                "folder": get_backup_folder()
            }
        elif response.status_code == 401:
            return {
                "connected": False,
                "error": "Недействительный или просроченный OAuth токен Яндекс.Диска."
            }
        else:
            return {
                "connected": False,
                "error": f"Ошибка Яндекс.Диск API (HTTP {response.status_code})"
            }
    except Exception as e:
        logger.error(f"Error checking Yandex Disk status: {e}")
        return {"connected": False, "error": str(e)}

def ensure_backup_folder_exists() -> bool:
    token = get_yandex_token()
    if not token:
        return False
        
    folder = get_backup_folder()
    try:
        # Try creating folder (status 409 means already exists, which is OK)
        url = f"{YANDEX_API_BASE}/resources"
        params = {"path": folder}
        res = requests.put(url, headers=get_headers(), params=params, timeout=10)
        if res.status_code in [201, 409]:
            return True
        return False
    except Exception as e:
        logger.error(f"Error ensuring backup folder exists: {e}")
        return False

def create_cloud_backup(note: str = "") -> Dict[str, Any]:
    token = get_yandex_token()
    if not token:
        return {
            "success": False,
            "error": "OAuth-токен Яндекс.Диска не указан в Настройках."
        }
        
    ensure_backup_folder_exists()
    
    dump_data = export_full_database_json()
    dump_data["backup_note"] = note
    json_bytes = json.dumps(dump_data, ensure_ascii=False, indent=2).encode('utf-8')
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"game_backlog_backup_{timestamp}.json"
    folder = get_backup_folder()
    full_path = f"{folder}/{filename}"
    
    try:
        # Step 1: Get upload link
        upload_link_url = f"{YANDEX_API_BASE}/resources/upload"
        params = {"path": full_path, "overwrite": "true"}
        res = requests.get(upload_link_url, headers=get_headers(), params=params, timeout=10)
        
        if res.status_code != 200:
            return {
                "success": False,
                "error": f"Не удалось получить ссылку для загрузки (HTTP {res.status_code}): {res.text}"
            }
            
        upload_href = res.json().get("href")
        
        # Step 2: Upload file data
        put_res = requests.put(upload_href, data=json_bytes, headers={"Content-Type": "application/json"}, timeout=30)
        
        if put_res.status_code in [201, 200]:
            return {
                "success": True,
                "filename": filename,
                "path": full_path,
                "size_bytes": len(json_bytes),
                "games_count": len(dump_data.get("games", [])),
                "timestamp": datetime.now().isoformat()
            }
        else:
            return {
                "success": False,
                "error": f"Ошибка передачи данных на Яндекс.Диск (HTTP {put_res.status_code})"
            }
    except Exception as e:
        logger.error(f"Error creating Yandex Disk backup: {e}")
        return {"success": False, "error": str(e)}

def list_cloud_backups() -> Dict[str, Any]:
    token = get_yandex_token()
    if not token:
        return {
            "success": False,
            "error": "OAuth-токен Яндекс.Диска не указан."
        }
        
    folder = get_backup_folder()
    try:
        url = f"{YANDEX_API_BASE}/resources"
        params = {
            "path": folder,
            "sort": "-created",
            "limit": 20
        }
        res = requests.get(url, headers=get_headers(), params=params, timeout=10)
        if res.status_code == 200:
            data = res.json()
            items = data.get("_embedded", {}).get("items", [])
            backups = []
            for item in items:
                if item.get("type") == "file" and item.get("name", "").endswith(".json"):
                    backups.append({
                        "name": item.get("name"),
                        "path": item.get("path"),
                        "size": item.get("size", 0),
                        "created": item.get("created", ""),
                        "modified": item.get("modified", "")
                    })
            return {"success": True, "backups": backups, "folder": folder}
        elif res.status_code == 404:
            return {"success": True, "backups": [], "folder": folder, "message": "Папка бэкапов пока не создана."}
        else:
            return {"success": False, "error": f"HTTP {res.status_code}: {res.text}"}
    except Exception as e:
        logger.error(f"Error listing backups from Yandex Disk: {e}")
        return {"success": False, "error": str(e)}

def restore_cloud_backup(backup_path: str) -> Dict[str, Any]:
    token = get_yandex_token()
    if not token:
        return {
            "success": False,
            "error": "OAuth-токен Яндекс.Диска не указан."
        }
        
    try:
        # Step 1: Get download link
        download_url = f"{YANDEX_API_BASE}/resources/download"
        params = {"path": backup_path}
        res = requests.get(download_url, headers=get_headers(), params=params, timeout=10)
        
        if res.status_code != 200:
            return {
                "success": False,
                "error": f"Не удалось получить ссылку на скачивание (HTTP {res.status_code})"
            }
            
        download_href = res.json().get("href")
        
        # Step 2: Download JSON content
        file_res = requests.get(download_href, timeout=30)
        if file_res.status_code != 200:
            return {
                "success": False,
                "error": f"Ошибка скачивания файла бэкапа (HTTP {file_res.status_code})"
            }
            
        data = file_res.json()
        
        # Step 3: Import into SQLite
        import_result = import_full_database_json(data)
        return {
            "success": True,
            "message": f"Успешно восстановлено: {import_result.get('imported_games', 0)} игр, {import_result.get('imported_sessions', 0)} игровых сессий.",
            "imported_games": import_result.get("imported_games", 0)
        }
    except Exception as e:
        logger.error(f"Error restoring backup from Yandex Disk: {e}")
        return {"success": False, "error": str(e)}


def delete_cloud_backup(backup_path: str) -> Dict[str, Any]:
    token = get_yandex_token()
    if not token:
        return {
            "success": False,
            "error": "OAuth-токен Яндекс.Диска не указан."
        }
        
    try:
        url = f"{YANDEX_API_BASE}/resources"
        params = {
            "path": backup_path,
            "permanently": "true"
        }
        res = requests.delete(url, headers=get_headers(), params=params, timeout=10)
        if res.status_code in [204, 202, 200]:
            return {
                "success": True,
                "message": "Резервная копия успешно удалена с Яндекс.Диска.",
                "deleted_path": backup_path
            }
        elif res.status_code == 404:
            return {
                "success": True,
                "message": "Файл уже отсутствует на Яндекс.Диске.",
                "deleted_path": backup_path
            }
        else:
            return {
                "success": False,
                "error": f"Ошибка удаления файла с Яндекс.Диска (HTTP {res.status_code}): {res.text}"
            }
    except Exception as e:
        logger.error(f"Error deleting backup from Yandex Disk: {e}")
        return {"success": False, "error": str(e)}
