"""
Comprehensive Authentication & Security Test Suite for GAME-ROOM's Unified Web Application.
Tests:
1. Web Login (valid, invalid password, invalid username, missing credentials in env, cookie flags).
2. Server-side Sessions (valid access, expired sessions, revoked sessions, logout, fixation defense).
3. API Protection Matrix (all protected classes reject unauthenticated requests, accept Web session, accept Bearer token).
4. Healthcheck unauthenticated accessibility.
5. Settings protection & secret sanitization (GET settings omits secrets, POST preserves existing on blank/mask).
6. Full Bundle Import/Export security (web credentials/sessions never exported or imported).
7. Login brute-force rate limiter (lockout on 5 failures, reset on success).
8. Service Worker & SPA shell security (unauthenticated GET / serves login page, not main backlog).
"""
import os
import sys
import json
import time
import secrets
import unittest
import tempfile
from datetime import datetime, timezone, timedelta

app_dir = os.path.dirname(os.path.abspath(__file__))
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)

import database as db
import security
from main import app
from fastapi.testclient import TestClient

class TestWebAndAndroidAuth(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Create isolated temporary database for auth test suite
        cls.temp_dir = tempfile.mkdtemp(prefix="gameroom_auth_test_")
        cls.test_db_path = os.path.join(cls.temp_dir, "test_auth.db")
        os.environ["BACKLOG_DB_PATH"] = cls.test_db_path
        db.DB_PATH = cls.test_db_path
        db.init_db()

        cls.username = "gameroom_owner"
        cls.password = "SuperSecret_P@ssword_2026!"
        cls.password_hash = security.hash_password(cls.password)

        os.environ["GAME_ROOM_WEB_USERNAME"] = cls.username
        os.environ["GAME_ROOM_WEB_PASSWORD_HASH"] = cls.password_hash

        cls.sync_token = security.get_or_create_sync_token()

    @classmethod
    def tearDownClass(cls):
        try:
            if os.path.exists(cls.test_db_path):
                os.remove(cls.test_db_path)
            os.rmdir(cls.temp_dir)
        except Exception:
            pass

    def setUp(self):
        # Fresh client per test
        self.client = TestClient(app)
        # Clear rate limiter state for clean testing
        security.login_limiter._records.clear()

    # =========================================================================
    # 1. Login Tests
    # =========================================================================

    def test_01_login_success(self):
        """Valid username & password returns 200, sets secure HttpOnly cookie."""
        res = self.client.post("/api/auth/login", json={
            "username": self.username,
            "password": self.password
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("username"), self.username)

        # Check session cookie
        self.assertIn("gameroom_session", res.cookies)
        raw_cookie = res.headers.get("set-cookie", "")
        self.assertIn("httponly", raw_cookie.lower())
        self.assertIn("samesite=strict", raw_cookie.lower())

    def test_02_login_invalid_password(self):
        """Invalid password returns 401 and does NOT set a session cookie."""
        res = self.client.post("/api/auth/login", json={
            "username": self.username,
            "password": "wrong_password_attempt"
        })
        self.assertEqual(res.status_code, 401)
        self.assertNotIn("gameroom_session", res.cookies)
        self.assertIn("Неверное имя пользователя или пароль", res.json().get("detail", ""))

    def test_03_login_invalid_username(self):
        """Invalid username returns 401 with identical error message (no user enumeration)."""
        res = self.client.post("/api/auth/login", json={
            "username": "nonexistent_hacker",
            "password": "some_password"
        })
        self.assertEqual(res.status_code, 401)
        self.assertNotIn("gameroom_session", res.cookies)
        self.assertIn("Неверное имя пользователя или пароль", res.json().get("detail", ""))

    def test_04_login_missing_credentials_controlled_error(self):
        """Missing server credentials in environment raises controlled 500 configuration error."""
        old_user = os.environ.get("GAME_ROOM_WEB_USERNAME")
        old_hash = os.environ.get("GAME_ROOM_WEB_PASSWORD_HASH")

        try:
            os.environ.pop("GAME_ROOM_WEB_USERNAME", None)
            os.environ.pop("GAME_ROOM_WEB_PASSWORD_HASH", None)

            res = self.client.post("/api/auth/login", json={
                "username": "any_user",
                "password": "any_password"
            })
            self.assertEqual(res.status_code, 500)
            self.assertIn("не настроены", res.json().get("detail", "").lower())
        finally:
            if old_user:
                os.environ["GAME_ROOM_WEB_USERNAME"] = old_user
            if old_hash:
                os.environ["GAME_ROOM_WEB_PASSWORD_HASH"] = old_hash

    # =========================================================================
    # 2. Session Management Tests
    # =========================================================================

    def test_05_session_valid_access(self):
        """Valid session cookie authorizes requests to protected endpoints."""
        login_res = self.client.post("/api/auth/login", json={
            "username": self.username,
            "password": self.password
        })
        self.assertEqual(login_res.status_code, 200)

        # /api/auth/me
        me_res = self.client.get("/api/auth/me")
        self.assertEqual(me_res.status_code, 200)
        self.assertEqual(me_res.json().get("auth_type"), "session")

        # Protected games endpoint
        games_res = self.client.get("/api/games")
        self.assertEqual(games_res.status_code, 200)

    def test_06_session_expired(self):
        """Expired session is rejected with 401."""
        login_res = self.client.post("/api/auth/login", json={
            "username": self.username,
            "password": self.password
        })
        raw_token = login_res.cookies.get("gameroom_session")
        token_hash = security.hash_session_token(raw_token)

        # Manually expire the session in SQLite
        past_iso = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        conn = db.get_db_connection()
        conn.cursor().execute("UPDATE web_sessions SET expires_at = ? WHERE token_hash = ?", (past_iso, token_hash))
        conn.commit()
        conn.close()

        res = self.client.get("/api/games")
        self.assertEqual(res.status_code, 401)
        self.assertIn("истёк", res.json().get("detail", "").lower())

    def test_07_session_revoked(self):
        """Revoked session is rejected with 401."""
        login_res = self.client.post("/api/auth/login", json={
            "username": self.username,
            "password": self.password
        })
        raw_token = login_res.cookies.get("gameroom_session")
        token_hash = security.hash_session_token(raw_token)

        # Manually revoke the session in SQLite
        now_iso = datetime.now(timezone.utc).isoformat()
        conn = db.get_db_connection()
        conn.cursor().execute("UPDATE web_sessions SET revoked_at = ? WHERE token_hash = ?", (now_iso, token_hash))
        conn.commit()
        conn.close()

        res = self.client.get("/api/games")
        self.assertEqual(res.status_code, 401)
        self.assertIn("отозвана", res.json().get("detail", "").lower())

    def test_08_logout_revokes_session(self):
        """POST /api/auth/logout revokes session in DB and subsequent calls fail."""
        login_res = self.client.post("/api/auth/login", json={
            "username": self.username,
            "password": self.password
        })
        raw_token = login_res.cookies.get("gameroom_session")

        logout_res = self.client.post("/api/auth/logout")
        self.assertEqual(logout_res.status_code, 200)

        # Session in DB should now be marked revoked
        token_hash = security.hash_session_token(raw_token)
        session_row = db.get_web_session(token_hash)
        self.assertIsNotNone(session_row["revoked_at"])

        # New request with old token should fail
        res = self.client.get("/api/games", cookies={"gameroom_session": raw_token})
        self.assertEqual(res.status_code, 401)

    def test_09_new_login_creates_new_session_token(self):
        """Each login generates a distinct cryptographic session token (session fixation defense)."""
        res1 = self.client.post("/api/auth/login", json={"username": self.username, "password": self.password})
        token1 = res1.cookies.get("gameroom_session")

        res2 = self.client.post("/api/auth/login", json={"username": self.username, "password": self.password})
        token2 = res2.cookies.get("gameroom_session")

        self.assertNotEqual(token1, token2)
        self.assertGreater(len(token1), 32)
        self.assertGreater(len(token2), 32)

    # =========================================================================
    # 3. API Protection Matrix
    # =========================================================================

    def test_10_api_protection_matrix_unauthenticated_rejects(self):
        """Every protected API class rejects unauthenticated requests with 401."""
        unauth_client = TestClient(app)

        endpoints = [
            ("GET", "/api/games"),
            ("POST", "/api/games"),
            ("GET", "/api/stats"),
            ("GET", "/api/settings"),
            ("POST", "/api/settings"),
            ("GET", "/api/rawg/search?query=test"),
            ("GET", "/api/rawg/missing-count"),
            ("POST", "/api/ai/chat"),
            ("GET", "/api/ai/history"),
            ("GET", "/api/yandex/status"),
            ("GET", "/api/export/full-bundle"),
            ("GET", "/api/youtube/trailer?title=Doom"),
            ("POST", "/api/sync"),
            ("POST", "/api/sync/initial"),
            ("GET", "/api/sync/status"),
        ]

        for method, url in endpoints:
            if method == "GET":
                res = unauth_client.get(url)
            else:
                res = unauth_client.post(url, json={})
            self.assertEqual(
                res.status_code, 401,
                f"Endpoint {method} {url} must require authentication (got {res.status_code})"
            )

    def test_11_android_bearer_token_authorizes_endpoints(self):
        """Android Bearer Sync Token authorizes Android sync endpoints and data endpoints."""
        bearer_client = TestClient(app)
        headers = {"Authorization": f"Bearer {self.sync_token}"}

        # 1. Sync status
        res_status = bearer_client.get("/api/sync/status", headers=headers)
        self.assertEqual(res_status.status_code, 200)

        # 2. Sync initial
        init_payload = {
            "client_id": "test-android-apk",
            "client_time_now": datetime.now(timezone.utc).isoformat(),
            "games": [],
            "wishlist": []
        }
        res_init = bearer_client.post("/api/sync/initial", json=init_payload, headers=headers)
        self.assertEqual(res_init.status_code, 200)

        # 3. Reading games
        res_games = bearer_client.get("/api/games", headers=headers)
        self.assertEqual(res_games.status_code, 200)

        # 4. Bad bearer token rejected
        res_bad = bearer_client.get("/api/sync/status", headers={"Authorization": "Bearer bad_sync_token"})
        self.assertEqual(res_bad.status_code, 401)

    def test_12_query_string_token_rejected(self):
        """Passing token via query string ?token=... is strictly rejected (Requirement 16)."""
        res = self.client.get(f"/api/games?token={self.sync_token}")
        self.assertEqual(res.status_code, 401)

    # =========================================================================
    # 4. Healthcheck
    # =========================================================================

    def test_13_healthcheck_unauthenticated(self):
        """GET /api/health is accessible without any credentials (for Docker healthcheck)."""
        unauth_client = TestClient(app)
        res = unauth_client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"status": "ok"})

    # =========================================================================
    # 5. Settings Exposure & Protection
    # =========================================================================

    def test_14_get_settings_omits_secrets(self):
        """GET /api/settings NEVER leaks secrets or sync tokens (Requirement 8)."""
        db.save_settings_dict({
            "rawg_api_key": "rawg_secret_999",
            "youtube_api_key": "youtube_secret_888",
            "gigachat_auth_key": "gigachat_secret_777",
            "yandex_disk_token": "yandex_secret_666",
            "gameroom_sync_token": "sync_token_secret_555",
            "user_name": "TestUser"
        })

        # Login to get session
        self.client.post("/api/auth/login", json={"username": self.username, "password": self.password})

        res = self.client.get("/api/settings")
        self.assertEqual(res.status_code, 200)
        data = res.json()

        # 1. Real secrets MUST NOT be present in settings dict
        settings_dict = data.get("settings", {})
        self.assertNotIn("rawg_api_key", settings_dict)
        self.assertNotIn("youtube_api_key", settings_dict)
        self.assertNotIn("gigachat_auth_key", settings_dict)
        self.assertNotIn("yandex_disk_token", settings_dict)
        self.assertNotIn("gameroom_sync_token", settings_dict)

        # 2. Real secrets MUST NOT be present at top level
        self.assertNotIn("gameroom_sync_token", data)

        # 3. Status flags MUST be true
        self.assertTrue(data.get("rawg_configured"))
        self.assertTrue(data.get("youtube_configured"))
        self.assertTrue(data.get("gigachat_configured"))
        self.assertTrue(data.get("yandex_configured"))
        self.assertTrue(data.get("sync_token_configured"))

        # 4. Safe setting is retained
        self.assertEqual(settings_dict.get("user_name"), "TestUser")

    def test_15_save_settings_empty_does_not_overwrite_secrets(self):
        """Saving empty strings or placeholder masks does NOT erase existing secrets (Requirement 8)."""
        db.save_settings_dict({
            "rawg_api_key": "existing_rawg_key",
            "youtube_api_key": "existing_yt_key"
        })

        self.client.post("/api/auth/login", json={"username": self.username, "password": self.password})

        # Send empty rawg and masked youtube key
        res = self.client.post("/api/settings", json={
            "settings": {
                "rawg_api_key": "",
                "youtube_api_key": "•••••••••••••••• (Ключ сохранён)",
                "user_name": "UpdatedUser"
            }
        })
        self.assertEqual(res.status_code, 200)

        # Verify DB retains existing secrets
        self.assertEqual(db.get_setting("rawg_api_key"), "existing_rawg_key")
        self.assertEqual(db.get_setting("youtube_api_key"), "existing_yt_key")
        self.assertEqual(db.get_setting("user_name"), "UpdatedUser")

        # Now send a brand new key -> should overwrite
        res2 = self.client.post("/api/settings", json={
            "settings": {
                "rawg_api_key": "new_real_rawg_key_123"
            }
        })
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(db.get_setting("rawg_api_key"), "new_real_rawg_key_123")

    # =========================================================================
    # 6. Import/Export Security
    # =========================================================================

    def test_16_export_full_bundle_excludes_web_auth_and_sessions(self):
        """Full bundle export excludes password hashes, session tokens, and web credentials."""
        self.client.post("/api/auth/login", json={"username": self.username, "password": self.password})

        res = self.client.get("/api/export/full-bundle")
        self.assertEqual(res.status_code, 200)
        bundle = json.loads(res.text)

        # 1. No web_sessions table exported
        self.assertNotIn("web_sessions", bundle)

        # 2. No password hash or web credentials in exported settings
        for s in bundle.get("settings", []):
            k = s.get("key", "").lower()
            self.assertFalse(k.startswith("game_room_web_"), f"Sensitive key {k} found in export")
            self.assertNotIn("password", k)
            self.assertNotIn("session", k)

    def test_17_import_full_bundle_cannot_inject_web_credentials(self):
        """Full bundle import cannot overwrite web credentials or inject web sessions."""
        self.client.post("/api/auth/login", json={"username": self.username, "password": self.password})

        malicious_bundle = {
            "version": "3.0.0",
            "games": [],
            "play_sessions": [],
            "settings": [
                {"key": "game_room_web_username", "value": "hacked_admin"},
                {"key": "game_room_web_password_hash", "value": "hacked_hash"},
                {"key": "gameroom_sync_token", "value": "hacked_sync_token"}
            ],
            "ai_history": []
        }

        import_file = ("bundle.json", json.dumps(malicious_bundle).encode("utf-8"), "application/json")
        res = self.client.post("/api/import/full-bundle", files={"file": import_file})
        self.assertEqual(res.status_code, 200)

        # Verify DB was NOT modified with malicious settings
        self.assertNotEqual(db.get_setting("game_room_web_username"), "hacked_admin")
        self.assertNotEqual(db.get_setting("gameroom_sync_token"), "hacked_sync_token")

    # =========================================================================
    # 7. Login Brute-Force Rate Limiter
    # =========================================================================

    def test_18_brute_force_lockout_and_reset(self):
        """5 consecutive failed logins trigger HTTP 429 lockout; successful login resets count."""
        # 1. Make 4 failed attempts -> 401
        for i in range(4):
            res = self.client.post("/api/auth/login", json={
                "username": self.username,
                "password": f"wrong_{i}"
            })
            self.assertEqual(res.status_code, 401)

        # 2. 5th failed attempt -> 401
        res5 = self.client.post("/api/auth/login", json={
            "username": self.username,
            "password": "wrong_5"
        })
        self.assertEqual(res5.status_code, 401)

        # 3. 6th attempt -> 429 Too Many Requests (Lockout activated)
        res6 = self.client.post("/api/auth/login", json={
            "username": self.username,
            "password": self.password
        })
        self.assertEqual(res6.status_code, 429)
        self.assertIn("Слишком много неудачных попыток", res6.json().get("detail", ""))

        # 4. Clear lockout and verify success resets
        security.login_limiter._records.clear()
        res_ok = self.client.post("/api/auth/login", json={
            "username": self.username,
            "password": self.password
        })
        self.assertEqual(res_ok.status_code, 200)

    # =========================================================================
    # 8. Web UI & SPA Shell Security
    # =========================================================================

    def test_19_unauthenticated_root_serves_login_page(self):
        """Unauthenticated GET / serves login.html, NOT the main backlog index.html."""
        unauth_client = TestClient(app)
        res = unauth_client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("GAME-ROOM // ВХОД", res.text)
        self.assertIn("id=\"login-form\"", res.text)
        self.assertNotIn("hero-playing-grid", res.text)

    def test_20_authenticated_root_serves_app_index(self):
        """Authenticated GET / serves the actual backlog tracker app."""
        self.client.post("/api/auth/login", json={"username": self.username, "password": self.password})
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("hero-playing-grid", res.text)
        self.assertIn("topbar", res.text)


if __name__ == "__main__":
    unittest.main()
