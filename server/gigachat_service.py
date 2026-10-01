"""
GigaChat (Sber Giga API) AI Assistant Integration Service
Features dense low-token context compression, gamer profiling, backlog clearance
roadmaps, and tactical gameplay consulting.
"""
import requests
import uuid
import time
import json
import logging
import urllib3
from typing import Dict, Any, List, Optional
from database import (
    get_setting, get_games, get_stats, 
    save_ai_message, get_ai_history
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger("gigachat_service")

GIGACHAT_OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
GIGACHAT_API_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"

_cached_token = {
    "access_token": "",
    "expires_at": 0
}

def get_gigachat_token() -> Optional[str]:
    auth_key = get_setting("gigachat_auth_key", "").strip()
    if not auth_key:
        return None
        
    if auth_key.startswith("eyJ") and len(auth_key) > 80:
        return auth_key

    now_ts = int(time.time()) * 1000
    if _cached_token["access_token"] and _cached_token["expires_at"] > (now_ts + 60000):
        return _cached_token["access_token"]
        
    scope = get_setting("gigachat_scope", "GIGACHAT_API_PERS").strip() or "GIGACHAT_API_PERS"
    
    try:
        rquid = str(uuid.uuid4())
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "RqUID": rquid,
            "Authorization": f"Basic {auth_key}"
        }
        data = {"scope": scope}
        
        response = requests.post(
            GIGACHAT_OAUTH_URL, 
            headers=headers, 
            data=data, 
            timeout=15,
            verify=False
        )
        
        if response.status_code == 200:
            res_json = response.json()
            token = res_json.get("access_token")
            expires_at = res_json.get("expires_at", 0)
            _cached_token["access_token"] = token
            _cached_token["expires_at"] = expires_at
            return token
        else:
            logger.error(f"GigaChat OAuth failed: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.error(f"GigaChat token fetch error: {e}")
        return None

def build_dense_context() -> str:
    """
    Builds a high-signal, ultra-compact text summary of the library
    to minimize token usage while giving the AI full situational awareness.
    """
    user_name = get_setting("user_name", "Геймер")
    stats = get_stats()
    
    playing_games = get_games(status="playing")
    backlog_games = get_games(status="backlog")
    wishlist_games = get_games(status="wishlist")
    completed_games = get_games(status="completed")
    
    # 1. Playing lines
    playing_lines = []
    for g in playing_games:
        h_done = round(g['user_playtime_minutes'] / 60.0, 1)
        h_est = g['playtime_main'] or 10.0
        note_str = f" ({g['notes']})" if g.get('notes') else ""
        playing_lines.append(f"• [ИГРАЕТ] {g['title']} | {g['platform']} | {g['genres']} | {h_done}ч из ~{h_est}ч{note_str}")

    # 2. Backlog lines (compact grouped)
    backlog_lines = []
    for g in backlog_games[:12]:
        prio_mark = "🔥" if g['priority'] in ['urgent', 'high'] else "⭐"
        backlog_lines.append(f"• [БЭКЛОГ {prio_mark}] {g['title']} | {g['platform']} | ~{g['playtime_main']}ч | {g['genres']}")

    # 3. Completed lines (with StopGame rating grades)
    grade_ru = {
        "izumitelno": "ИЗУМИТЕЛЬНО 👑",
        "pohvalno": "ПОХВАЛЬНО 🥇",
        "prohodnyak": "ПРОХОДНЯК 🥈",
        "musor": "МУСОР 🗑️"
    }
    completed_lines = []
    for g in completed_games[:10]:
        g_grade = grade_ru.get(g.get("rating_grade"), f"Оценка {g.get('user_score', '-')}")
        h_comp = round(g['user_playtime_minutes'] / 60.0, 1)
        rev_str = f" | Отзыв: {g['user_review']}" if g.get('user_review') else ""
        completed_lines.append(f"• [ПРОЙДЕНО] {g['title']} -> {g_grade} (наиграно {h_comp}ч){rev_str}")

    # 4. Wishlist lines
    wishlist_lines = [f"• [ВИШЛИСТ] {g['title']} ({g.get('release_date') or 'TBA'})" for g in wishlist_games[:6]]

    context_block = f"""[БИБЛИОТЕКА ИГРОКА: {user_name}]
Статистика: Всего {stats['total_games']} игр | Играет: {stats['playing_count']} | Бэклог: {stats['backlog_count']} (~{stats['backlog_total_hours']}ч) | Пройдено: {stats['completed_count']} | Наиграно всего: {stats['total_playtime_hours']}ч.
Оценки пройденных (система StopGame): Изумительно={stats['grade_counts']['izumitelno']}, Похвально={stats['grade_counts']['pohvalno']}, Проходняк={stats['grade_counts']['prohodnyak']}, Мусор={stats['grade_counts']['musor']}.

АКТИВНЫЕ ИГРЫ:
{chr(10).join(playing_lines) if playing_lines else "Нет активных игр."}

ТОП БЭКЛОГА:
{chr(10).join(backlog_lines) if backlog_lines else "Бэклог пуст."}

ПРОЙДЕННЫЕ:
{chr(10).join(completed_lines) if completed_lines else "Пока нет."}

ВИШЛИСТ:
{chr(10).join(wishlist_lines) if wishlist_lines else "Вишлист пуст."}
"""
    return context_block

def build_system_prompt(action_type: str = "chat") -> str:
    user_name = get_setting("user_name", "Геймер")
    context = build_dense_context()

    base_instructions = f"""Ты — персональный AI-штурман и гейм-эксперт приложения GAME-ROOM's.
Имя пользователя: {user_name}.

{context}

Твои возможности:
1. Глубокий анализ вкусов и составление психологического портрета геймера по оценкам ('Изумительно', 'Похвально', 'Проходняк', 'Мусор') и жанрам.
2. Интеллектуальный подбор игр из бэклога под конкретный бюджет времени, платформу и настроение.
3. Советы по тактике, билдам, настройке и прохождению активных игр без жестких спойлеров.
4. Расчет дорожной карты зачистки бэклога.
5. Стиль: умный, энергичный, лаконичный, геймерский и структурированный (в эстетике Cyber Comic / Spider-Verse). Выделяй главное жирным шрифтом и списками.
"""
    return base_instructions

def generate_ai_response(
    user_message: str, 
    history: Optional[List[Dict[str, str]]] = None, 
    include_context: bool = True,
    action_type: str = "chat"
) -> Dict[str, Any]:
    save_ai_message(role="user", content=user_message, action_type=action_type)
    
    token = get_gigachat_token()
    
    if not token:
        local_reply = generate_local_smart_response(user_message, action_type)
        save_ai_message(role="assistant", content=local_reply["reply"], action_type=action_type)
        return local_reply

    messages = [
        {"role": "system", "content": build_system_prompt(action_type)}
    ]
    
    if history:
        for h in history[-6:]:
            messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
            
    messages.append({"role": "user", "content": user_message})
    
    try:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}"
        }
        payload = {
            "model": "GigaChat",
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 1200
        }
        
        response = requests.post(
            GIGACHAT_API_URL, 
            headers=headers, 
            json=payload, 
            timeout=30,
            verify=False
        )
        
        if response.status_code == 200:
            res_json = response.json()
            reply_text = res_json["choices"][0]["message"]["content"]
            save_ai_message(role="assistant", content=reply_text, action_type=action_type)
            return {
                "success": True,
                "provider": "GigaChat AI (Sber Giga API)",
                "reply": reply_text
            }
        else:
            logger.error(f"GigaChat API error: {response.status_code} - {response.text}")
            local_fallback = generate_local_smart_response(user_message, action_type)
            save_ai_message(role="assistant", content=local_fallback["reply"], action_type=action_type)
            return {
                "success": False,
                "error": f"Ошибка GigaChat API: {response.status_code}",
                "reply": local_fallback["reply"]
            }
    except Exception as e:
        logger.error(f"Error calling GigaChat: {e}")
        local_fallback = generate_local_smart_response(user_message, action_type)
        save_ai_message(role="assistant", content=local_fallback["reply"], action_type=action_type)
        return local_fallback

def generate_local_smart_response(message: str, action_type: str = "chat") -> Dict[str, Any]:
    msg_lower = message.lower()
    stats = get_stats()
    playing = get_games(status="playing")
    backlog = get_games(status="backlog")
    wishlist = get_games(status="wishlist")
    completed = get_games(status="completed")
    
    # 1. Gamer Portrait Builder
    if action_type == "portrait" or any(w in msg_lower for w in ["портрет", "психологическ", "мой вкус", "кто я", "анализ игрока"]):
        izum = [g['title'] for g in completed if g.get('rating_grade') == 'izumitelno']
        pohv = [g['title'] for g in completed if g.get('rating_grade') == 'pohvalno']
        
        reply = f"🧠 **ГЕЙМЕРСКИЙ ПОРТРЕТ // GAME-ROOM's ANALYTICS**\n\n"
        reply += f"На основе анализа твоей библиотеки ({stats['total_games']} игр, {stats['total_playtime_hours']} наигранных часов):\n\n"
        reply += f"🎯 **Игровой архетип:** *«Кинематографичный эстет & Ценитель плотного повествования»*\n"
        reply += f"Ты ценишь авторский визуал, глубокую атмосферу и качественную подачу без искусственного растягивания геймплея.\n\n"
        if izum:
            reply += f"👑 **Золотой эталон (Изумительно):** {', '.join(izum)}\n"
        if pohv:
            reply += f"🥇 **Высокий стандарт (Похвально):** {', '.join(pohv)}\n\n"
        reply += f"⏱️ **Средняя комфортная сессия:** 10–25 часов на сюжет. Рекомендуется избегать монотонных MMO и бесконечного гринда в пользу законченных сюжетных арок."
        return {"success": True, "provider": "Local Navigator", "reply": reply}

    # 2. Suggest Next
    if action_type == "suggest_next" or any(w in msg_lower for w in ["что пройти", "что поиграть", "выбрать", "посоветуй", "следующ"]):
        if playing:
            top_p = playing[0]
            done_h = round(top_p['user_playtime_minutes'] / 60.0, 1)
            rem_h = max(0.5, round(top_p['playtime_main'] - done_h, 1))
            reply = f"🎯 **РЕКОМЕНДАЦИЯ ШТУРМАНА:**\n\n"
            reply += f"1️⃣ **Приоритет №1 — Добить активный тайтл:**\n"
            reply += f"Ты сейчас проходишь **{top_p['title']}** ({top_p['platform']}). Наиграно **{done_h}ч** из ~**{top_p['playtime_main']}ч** (осталось всего ~**{rem_h}ч**!). Дожми финал, чтобы закрыть гештальт.\n\n"
            if backlog:
                next_b = backlog[0]
                reply += f"2️⃣ **Следующий кандидат из бэклога:**\n"
                reply += f"👉 **{next_b['title']}** ({next_b['platform']}, ~{next_b['playtime_main']}ч, жанры: {next_b['genres']})."
            return {"success": True, "provider": "Local Navigator", "reply": reply}
        elif backlog:
            short_g = [g for g in backlog if g['playtime_main'] <= 15]
            target = short_g[0] if short_g else backlog[0]
            reply = f"⚡ **ИДЕАЛЬНЫЙ СТАРТ ИЗ БЭКЛОГА:**\n\n"
            reply += f"Возьми **{target['title']}**:\n"
            reply += f"- **Платформа:** {target['platform']}\n"
            reply += f"- **Жанр:** {target['genres']}\n"
            reply += f"- **Время:** ~{target['playtime_main']} ч.\n"
            reply += f"- **Оценка RAWG:** ⭐ {target['rawg_rating']}/5\n\n"
            reply += f"Плотный сюжетный опыт на 2–3 уютных вечера!"
            return {"success": True, "provider": "Local Navigator", "reply": reply}

    # 3. Backlog Plan
    if action_type == "backlog_plan" or any(w in msg_lower for w in ["план", "график", "расчет", "сколько времени", "зачистк"]):
        total_h = stats.get('backlog_total_hours', 0)
        weeks_5h = round(total_h / 5, 1) if total_h > 0 else 0
        weeks_10h = round(total_h / 10, 1) if total_h > 0 else 0
        
        reply = f"📅 **ДОРОЖНАЯ КАРТА ЗАЧИСТКИ БЭКЛОГА:**\n\n"
        reply += f"- 📚 Всего в очереди: **{len(backlog)}** игр (~**{total_h}** часов сюжета)\n"
        reply += f"- ⚡ При темпе **5 ч/неделю**: зачистка займет ~**{weeks_5h}** недель (~{round(weeks_5h/4, 1)} мес.)\n"
        reply += f"- 🚀 При темпе **10 ч/неделю**: зачистка займет ~**{weeks_10h}** недель (~{round(weeks_10h/4, 1)} мес.)\n\n"
        reply += f"**Стратегия:** Чередовать одну короткую игру (<10ч) с одной масштабной (>25ч), чтобы не выгорать."
        return {"success": True, "provider": "Local Navigator", "reply": reply}

    return {
        "success": True,
        "provider": "Local Navigator",
        "reply": f"🤖 **Штурман GAME-ROOM's на связи!**\n\nВ твоей базе **{stats['total_games']} игр** (наиграно {stats['total_playtime_hours']}ч). Я готов анализировать бэклог, строить портрет геймера и давать советы.\n\n💡 *Для активации нейросетевых ответов укажи авторизационный ключ GigaChat в Настройках.*"
    }
