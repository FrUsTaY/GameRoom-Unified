"""
Security and authentication layer for GAME-ROOM's Backlog Application
Handles Bearer Token authentication for the distributed Sync API.
"""
from typing import Optional
from fastapi import Header, HTTPException, Query, Request
import database as db

def get_or_create_sync_token() -> str:
    token = db.get_setting("gameroom_sync_token")
    if not token or not token.strip():
        import secrets
        token = secrets.token_urlsafe(32)
        db.set_setting("gameroom_sync_token", token)
    return token

def verify_sync_token(
    authorization: Optional[str] = Header(None),
    x_gameroom_token: Optional[str] = Header(None, alias="X-Gameroom-Token"),
    token_query: Optional[str] = Query(None, alias="token")
) -> bool:
    server_token = get_or_create_sync_token()
    
    provided_token = None
    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            provided_token = parts[1].strip()
        else:
            provided_token = authorization.strip()
    elif x_gameroom_token:
        provided_token = x_gameroom_token.strip()
    elif token_query:
        provided_token = token_query.strip()
        
    if not provided_token or provided_token != server_token:
        raise HTTPException(
            status_code=401,
            detail="Недействительный или отсутствующий токен синхронизации (Sync Token)."
        )
    return True
