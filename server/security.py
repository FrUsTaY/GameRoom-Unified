"""
Security and authentication layer for GAME-ROOM's Backlog Application.
Implements:
1. Android Bearer Sync Token verification (preserving full APK v1.0.0 compatibility).
2. Server-side Web Sessions with SHA-256 token hashing and HttpOnly SameSite=Strict cookies.
3. Argon2id password hashing and verification with constant-time dummy checking.
4. Bounded in-memory login brute-force protection (lockout after repeated failures).
5. CSRF protection for cookie-based state-changing requests.
6. Unified auth dependency accepting either a valid Web session or Android Bearer Sync Token.
"""
import os
import time
import secrets
import hashlib
import threading
from urllib.parse import urlparse
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Tuple
from collections import OrderedDict

from fastapi import Request, Response, Header, HTTPException
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError

import database as db

# --- Argon2id Password Hasher Setup ---
password_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16
)

# Precomputed dummy hash to prevent timing attacks when an invalid username is tested
DUMMY_ARGON2_HASH = password_hasher.hash("gameroom_dummy_timing_protection_value")

# Session cookie name and configuration
SESSION_COOKIE_NAME = "gameroom_session"
SESSION_DURATION_DAYS = 30


# --- Web Credentials (Environment-driven) ---

def get_web_credentials() -> Tuple[str, str]:
    """
    Retrieves web credentials from environment variables.
    Credentials must never be hardcoded or committed to git.
    """
    username = os.environ.get("GAME_ROOM_WEB_USERNAME", "").strip()
    password_hash = os.environ.get("GAME_ROOM_WEB_PASSWORD_HASH", "").strip()
    return username, password_hash

def has_web_credentials() -> bool:
    """Returns True if both web username and password hash are configured."""
    username, password_hash = get_web_credentials()
    return bool(username and password_hash)

def hash_password(plain_password: str) -> str:
    """Generates an Argon2id hash for the given plain text password."""
    if not plain_password:
        raise ValueError("Password cannot be empty")
    return password_hasher.hash(plain_password)

def verify_password(stored_hash: str, plain_password: str) -> bool:
    """Verifies a plain text password against an Argon2id hash."""
    try:
        return password_hasher.verify(stored_hash, plain_password)
    except (VerifyMismatchError, InvalidHashError, Exception):
        return False


# --- Android Sync Token ---

def get_or_create_sync_token() -> str:
    """
    Retrieves or generates the Android Sync Token.
    Can be overridden via GAMEROOM_SYNC_TOKEN environment variable.
    """
    env_token = os.environ.get("GAMEROOM_SYNC_TOKEN", "").strip()
    if env_token:
        # Keep database setting in sync if set via env
        db_token = db.get_setting("gameroom_sync_token")
        if db_token != env_token:
            db.set_setting("gameroom_sync_token", env_token)
        return env_token

    token = db.get_setting("gameroom_sync_token")
    if not token or not token.strip():
        token = secrets.token_urlsafe(32)
        db.set_setting("gameroom_sync_token", token)
    return token


# --- Login Brute-Force Rate Limiter ---

class LoginRateLimiter:
    """
    Thread-safe, bounded in-memory rate limiter for login brute-force protection.
    Limits repeated failed attempts by IP and locks out attackers with HTTP 429.
    Never trusts X-Forwarded-For unless TRUSTED_PROXIES is explicitly configured.
    """
    def __init__(self, max_attempts: int = 5, lockout_seconds: int = 300, max_tracked_ips: int = 1000):
        self.max_attempts = max_attempts
        self.lockout_seconds = lockout_seconds
        self.max_tracked_ips = max_tracked_ips
        self._lock = threading.Lock()
        self._records = OrderedDict()

    def _get_client_ip(self, request: Request) -> str:
        trusted = os.environ.get("TRUSTED_PROXIES", "").strip()
        if trusted:
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                return forwarded.split(",")[0].strip()
        if request.client and request.client.host:
            return request.client.host
        return "127.0.0.1"

    def check(self, request: Request):
        ip = self._get_client_ip(request)
        now = time.time()
        with self._lock:
            rec = self._records.get(ip)
            if rec:
                if rec["blocked_until"] > now:
                    retry_after = int(rec["blocked_until"] - now)
                    raise HTTPException(
                        status_code=429,
                        detail=f"Слишком много неудачных попыток входа. Пожалуйста, подождите {retry_after} сек.",
                        headers={"Retry-After": str(retry_after)}
                    )
                # Lockout period expired -> reset attempts
                if rec["blocked_until"] > 0 and rec["blocked_until"] <= now:
                    rec["attempts"] = 0
                    rec["blocked_until"] = 0.0

    def record_failure(self, request: Request):
        ip = self._get_client_ip(request)
        now = time.time()
        with self._lock:
            # Memory bounding: prune old or expired records if capacity reached
            if len(self._records) >= self.max_tracked_ips:
                expired = [k for k, v in self._records.items() if now - v["last_attempt"] > 3600]
                for k in expired:
                    self._records.pop(k, None)
                while len(self._records) >= self.max_tracked_ips:
                    self._records.popitem(last=False)

            rec = self._records.setdefault(ip, {"attempts": 0, "blocked_until": 0.0, "last_attempt": now})
            rec["last_attempt"] = now
            rec["attempts"] += 1
            if rec["attempts"] >= self.max_attempts:
                rec["blocked_until"] = now + self.lockout_seconds
            self._records.move_to_end(ip)

    def record_success(self, request: Request):
        ip = self._get_client_ip(request)
        with self._lock:
            if ip in self._records:
                del self._records[ip]

login_limiter = LoginRateLimiter()


# --- Session Management ---

def hash_session_token(token: str) -> str:
    """Computes SHA-256 hash of a session token for secure database storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

def is_cookie_secure(request: Request) -> bool:
    """
    Determines whether the Secure cookie flag should be set.
    Enabled if HTTPS, X-Forwarded-Proto is https, or COOKIE_SECURE is set.
    """
    force_secure = os.environ.get("COOKIE_SECURE", "").strip().lower()
    if force_secure in ("1", "true", "yes"):
        return True
    if force_secure in ("0", "false", "no"):
        return False
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"

def create_web_session(response: Response, request: Request) -> str:
    """
    Generates a cryptographically random session token, stores only its SHA-256 hash in SQLite,
    and sets an HttpOnly, SameSite=Strict cookie on the response.
    """
    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_session_token(raw_token)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=SESSION_DURATION_DAYS)).isoformat()

    db.create_web_session(token_hash, expires_at)

    secure_flag = is_cookie_secure(request)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        max_age=SESSION_DURATION_DAYS * 86400,
        httponly=True,
        samesite="strict",
        secure=secure_flag,
        path="/"
    )
    return raw_token

def revoke_session(session_token: str, response: Optional[Response] = None) -> bool:
    """
    Revokes the current server session in SQLite and clears the cookie if response provided.
    """
    if not session_token:
        return False
    token_hash = hash_session_token(session_token)
    success = db.revoke_web_session(token_hash)
    if response:
        response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return success

def is_valid_web_session(session_token: str) -> bool:
    """
    Validates whether the session token corresponds to an active, unrevoked, unexpired session in SQLite.
    """
    if not session_token:
        return False
    token_hash = hash_session_token(session_token)
    session = db.get_web_session(token_hash)
    if not session:
        return False
    if session.get("revoked_at"):
        return False

    try:
        exp_str = session.get("expires_at", "")
        # Handle trailing Z or offset
        if exp_str.endswith("Z"):
            exp_str = exp_str[:-1] + "+00:00"
        exp_dt = datetime.fromisoformat(exp_str)
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > exp_dt:
            return False
    except Exception:
        return False

    return True


# --- CSRF Protection for Web Sessions ---

def verify_csrf(request: Request):
    """
    Validates origin/referer for state-changing requests using cookie authentication.
    Bearer token requests (e.g. from Android) are exempt as they do not use ambient browser credentials.
    """
    sec_fetch_site = request.headers.get("sec-fetch-site")
    if sec_fetch_site in ("cross-site",):
        raise HTTPException(
            status_code=403,
            detail="Запрос заблокирован защитой от CSRF (Cross-Site Request Blocked)."
        )

    origin = request.headers.get("origin")
    host = request.headers.get("host")

    if origin and host:
        parsed_origin = urlparse(origin)
        origin_host = parsed_origin.netloc or parsed_origin.path
        if origin_host and origin_host.lower() != host.lower():
            raise HTTPException(
                status_code=403,
                detail="Запрос с другого источника заблокирован (CSRF Origin Mismatch)."
            )
    elif request.headers.get("referer") and host:
        referer = request.headers.get("referer")
        parsed_ref = urlparse(referer)
        ref_host = parsed_ref.netloc
        if ref_host and ref_host.lower() != host.lower():
            raise HTTPException(
                status_code=403,
                detail="Запрос с другого источника заблокирован (CSRF Referer Mismatch)."
            )


# --- Unified Authentication Dependency ---

def verify_auth(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_gameroom_token: Optional[str] = Header(None, alias="X-Gameroom-Token")
) -> Dict[str, Any]:
    """
    Unified Authentication Dependency:
    Accepts EITHER:
    1. Valid Android Bearer Sync Token via Authorization or X-Gameroom-Token header.
    2. Valid Web Server-Side Session via HttpOnly cookie.
    
    Strictly forbids passing tokens via URL query string or non-standard parameters.
    """
    # 1. Check Android / Bearer Token
    server_sync_token = get_or_create_sync_token()
    provided_bearer = None

    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            provided_bearer = parts[1].strip()
        else:
            provided_bearer = authorization.strip()
    elif x_gameroom_token:
        provided_bearer = x_gameroom_token.strip()

    if provided_bearer:
        if secrets.compare_digest(provided_bearer, server_sync_token):
            return {"auth_type": "bearer", "client": "android"}
        else:
            raise HTTPException(
                status_code=401,
                detail="Недействительный токен синхронизации Android (Sync Token)."
            )

    # 2. Check Web Session Cookie
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if session_token:
        token_hash = hash_session_token(session_token)
        session = db.get_web_session(token_hash)
        if not session:
            raise HTTPException(
                status_code=401,
                detail="Сессия не найдена или недействительна."
            )
        if session.get("revoked_at"):
            raise HTTPException(
                status_code=401,
                detail="Сессия была отозвана."
            )

        try:
            exp_str = session.get("expires_at", "")
            if exp_str.endswith("Z"):
                exp_str = exp_str[:-1] + "+00:00"
            exp_dt = datetime.fromisoformat(exp_str)
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) > exp_dt:
                raise HTTPException(
                    status_code=401,
                    detail="Срок действия сессии истёк."
                )
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                status_code=401,
                detail="Некорректная дата экспирации сессии."
            )

        # Enforce CSRF validation for state-changing requests using cookie session
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            verify_csrf(request)

        username, _ = get_web_credentials()
        return {"auth_type": "session", "user": username or "admin"}

    # 3. Neither valid Bearer token nor valid Web session
    raise HTTPException(
        status_code=401,
        detail="Требуется авторизация: войдите через веб-интерфейс или укажите Android Bearer Sync Token."
    )

# Backward-compatibility alias for sync routes and existing modules
verify_sync_token = verify_auth
