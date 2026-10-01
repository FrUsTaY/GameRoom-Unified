"""
Automated Test Suite for GAME-ROOM's Backlog Application
Tests Database, SVG Ratings, Russian Genres, RAWG Translation, GigaChat AI,
YouTube Trailer Integration, Backlog Randomizer Wheel, Yandex Cloud Backup & Deletion,
Full-Bundle Import/Export, and REST Endpoints.
"""
import sys
import os
import json
import unittest

app_dir = os.path.dirname(os.path.abspath(__file__))
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)

import database as db
import rawg_service as rawg
import gigachat_service as ai
import yandex_disk_service as yandex
import youtube_service as yt
import security
from fastapi.testclient import TestClient
from main import app

class GameRoomTestSuite(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import tempfile
        tmp_db = os.path.join(tempfile.gettempdir(), "test_gameroom.db")
        os.environ["BACKLOG_DB_PATH"] = tmp_db
        if os.path.exists(tmp_db):
            try:
                os.remove(tmp_db)
            except Exception:
                pass
        db.DB_PATH = tmp_db
        db.init_db()

        test_user = "test_suite_user"
        test_pass = "test_suite_secret_pass"
        os.environ["GAME_ROOM_WEB_USERNAME"] = test_user
        os.environ["GAME_ROOM_WEB_PASSWORD_HASH"] = security.hash_password(test_pass)

        cls.client = TestClient(app)
        login_resp = cls.client.post("/api/auth/login", json={"username": test_user, "password": test_pass})
        assert login_resp.status_code == 200, f"Test client login failed: {login_resp.text}"

    def test_01_db_initialization_and_seed(self):
        games = db.get_games()
        self.assertGreaterEqual(len(games), 5, "Database should contain starter seeded games")
        
        lana = next((g for g in games if "Lana" in g["title"]), None)
        self.assertIsNotNone(lana)
        self.assertEqual(lana.get("rating_grade"), "izumitelno", "Seeded completed game must have StopGame grade")
        self.assertIn("Платформер", lana.get("genres", ""), "Seeded game must have Russian genres")

    def test_02_svg_assets_exist(self):
        svg_dir = os.path.join(app_dir, "static", "assets", "ratings")
        for grade in ["izumitelno.svg", "pohvalno.svg", "prohodnyak.svg", "musor.svg"]:
            path = os.path.join(svg_dir, grade)
            self.assertTrue(os.path.exists(path), f"SVG asset {grade} must exist in {svg_dir}")
            self.assertGreater(os.path.getsize(path), 500, f"SVG asset {grade} must not be empty")

    def test_03_game_crud_with_russian_genres_and_ratings(self):
        new_game = {
            "title": "Cyberpunk 2077: Phantom Liberty",
            "slug": "cyberpunk-2077-phantom-liberty",
            "status": "completed",
            "platform": "PC",
            "genres": "Ролевая игра (RPG), Экшен, Киберпанк",
            "release_date": "2023-09-26",
            "playtime_main": 18.0,
            "user_playtime_minutes": 1200,
            "rating_grade": "pohvalno",
            "user_review": "Отличный шпионский триллер в Найт-Сити!",
            "priority": "high"
        }
        created = db.create_game(new_game)
        self.assertIsNotNone(created.get("id"))
        self.assertEqual(created.get("rating_grade"), "pohvalno")
        self.assertIn("Киберпанк", created.get("genres"))

        updated = db.update_game(created["id"], {"rating_grade": "izumitelno", "genres": "Экшен, Sci-Fi, Киберпанк"})
        self.assertEqual(updated.get("rating_grade"), "izumitelno")
        self.assertIn("Sci-Fi", updated.get("genres"))

        filtered = db.get_games(rating_grade="izumitelno")
        self.assertTrue(any(g["id"] == created["id"] for g in filtered))

        db.delete_game(created["id"])

    def test_04_rawg_russian_genre_translation_and_quick_add(self):
        # 1. Test translation helper
        raw_list = ["Action", "Adventure", "Shooter", "Open World", "Story Rich"]
        translated = rawg.translate_genres(raw_list)
        self.assertIn("Экшен", translated)
        self.assertIn("Приключения", translated)
        self.assertIn("Шутер", translated)
        self.assertIn("Открытый мир", translated)
        self.assertIn("Сюжетная", translated)

        # 2. Test RAWG Search & Quick Add
        res = self.client.get("/api/rawg/search?query=Witcher")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("results", data)
        self.assertGreater(len(data["results"]), 0)

        sample_item = data["results"][0]
        add_res = self.client.post("/api/rawg/quick-add", json={
            "rawg_id": sample_item.get("rawg_id"),
            "target_status": "backlog",
            "game_data": sample_item
        })
        self.assertEqual(add_res.status_code, 200)
        created_game = add_res.json()["game"]
        self.assertTrue(bool(created_game["genres"]))
        
        db.delete_game(created_game["id"])

    def test_05_gigachat_dense_context_and_gamer_portrait(self):
        context = ai.build_dense_context()
        self.assertIn("БИБЛИОТЕКА ИГРОКА", context)
        self.assertIn("АКТИВНЫЕ ИГРЫ", context)
        self.assertIn("ИЗУМИТЕЛЬНО", context)

        res = self.client.post("/api/ai/chat", json={
            "message": "Построй мой геймерский портрет.",
            "action_type": "portrait"
        })
        self.assertEqual(res.status_code, 200)
        chat_data = res.json()
        self.assertIn("reply", chat_data)
        self.assertIn("ПОРТРЕТ", chat_data["reply"])

        hist_res = self.client.get("/api/ai/history")
        self.assertEqual(hist_res.status_code, 200)
        history = hist_res.json()["history"]
        self.assertGreaterEqual(len(history), 2)

    def test_06_stats_with_stopgame_tiers(self):
        res = self.client.get("/api/stats")
        self.assertEqual(res.status_code, 200)
        stats = res.json()
        self.assertIn("grade_counts", stats)
        self.assertIn("izumitelno", stats["grade_counts"])
        self.assertIn("pohvalno", stats["grade_counts"])
        self.assertIn("prohodnyak", stats["grade_counts"])
        self.assertIn("musor", stats["grade_counts"])
        self.assertIn("top_genres", stats)

    def test_07_youtube_service_and_endpoints(self):
        # 1. Test curated starter game trailer lookup
        res = self.client.get("/api/youtube/trailer?title=Ghost+of+Tsushima&mode=trailer")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("success"))
        self.assertIn("primary_video", data)
        self.assertIn("embed_url", data["primary_video"])

        # 2. Test gameplay mode
        res_gp = self.client.get("/api/youtube/trailer?title=Ghost+of+Tsushima&mode=gameplay")
        self.assertEqual(res_gp.status_code, 200)
        data_gp = res_gp.json()
        self.assertTrue(data_gp.get("success"))

        # 3. Test unconfigured random title with graceful fallback
        res_rand = self.client.get("/api/youtube/trailer?title=UnknownGameRandom12345&mode=trailer")
        self.assertEqual(res_rand.status_code, 200)
        data_rand = res_rand.json()
        self.assertTrue(data_rand.get("requires_api_key"))
        self.assertIn("fallback_search_url", data_rand)

    def test_08_settings_with_youtube_key(self):
        save_res = self.client.post("/api/settings", json={
            "settings": {
                "youtube_api_key": "AIzaSyFakeKeyTest12345",
                "rawg_api_key": "test_rawg_key",
                "user_name": "Alex"
            }
        })
        self.assertEqual(save_res.status_code, 200)

        get_res = self.client.get("/api/settings")
        self.assertEqual(get_res.status_code, 200)
        s_data = get_res.json()
        self.assertTrue(s_data.get("is_youtube_configured"))
        self.assertTrue(s_data.get("youtube_configured"))
        # Security verification: secrets must NOT be exposed in GET /api/settings
        self.assertNotIn("youtube_api_key", s_data.get("settings", {}))
        self.assertNotIn("rawg_api_key", s_data.get("settings", {}))
        # Non-secret settings are safely returned
        self.assertEqual(s_data["settings"].get("user_name"), "Alex")
        # Internal DB correctly saved the secret
        self.assertEqual(db.get_setting("youtube_api_key"), "AIzaSyFakeKeyTest12345")

    def test_09_full_bundle_export_import_roundtrip(self):
        db.save_settings_dict({
            "rawg_api_key": "test_rawg_key_12345",
            "youtube_api_key": "test_yt_key_54321",
            "gigachat_auth_key": "test_giga_auth_secret_67890",
            "yandex_disk_token": "y0_test_oauth_token_abcde",
            "user_name": "Alex"
        })

        export_res = self.client.get("/api/export/full-bundle")
        self.assertEqual(export_res.status_code, 200)
        bundle = export_res.json()
        self.assertEqual(bundle.get("bundle_type"), "gameroom_full_export")
        self.assertEqual(bundle.get("version"), "3.0.0")
        self.assertGreaterEqual(len(bundle.get("games", [])), 5)
        self.assertGreaterEqual(len(bundle.get("settings", [])), 5)

        import_res = db.import_full_database_json(bundle)
        self.assertTrue(import_res.get("success"))
        self.assertGreaterEqual(import_res.get("imported_games", 0), 5)
        self.assertGreaterEqual(import_res.get("imported_settings", 0), 5)

    def test_10_static_html_modals_wheel_and_trailer(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.text
        self.assertIn("GAME-ROOM's", html)
        self.assertIn("randomizer-banner", html, "Randomizer banner must exist in Backlog")
        self.assertIn("btn-open-wheel", html, "Open Wheel button must exist")
        self.assertIn("trailer-modal", html, "YouTube Trailer modal must exist")
        self.assertIn("trailer-iframe", html, "Trailer iframe must exist")
        self.assertIn("wheel-modal", html, "Wheel Randomizer modal must exist")
        self.assertIn("app-dialog-modal", html, "Stylized confirm/alert modal must exist")
        self.assertIn("toast-container", html, "Toast container must exist")

    def test_11_yandex_delete_backup_endpoint(self):
        res = self.client.post("/api/yandex/delete", json={
            "backup_path": "disk:/GameBacklog_Backups/nonexistent_backup.json"
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("success", data)

if __name__ == "__main__":
    unittest.main()

    def test_12_move_and_clear_status_endpoints(self):
        # Create test games
        g1 = db.create_game({"title": "MoveTestGame1", "status": "wishlist"})
        g2 = db.create_game({"title": "MoveTestGame2", "status": "wishlist"})
        
        # Move wishlist -> backlog
        res = self.client.post("/api/games/move-status", json={
            "from_status": "wishlist",
            "to_status": "backlog"
        })
        self.assertEqual(res.status_code, 200)
        self.assertGreaterEqual(res.json().get("moved_count", 0), 2)
        
        # Clear test
        g3 = db.create_game({"title": "ClearTestGame", "status": "wishlist"})
        res2 = self.client.post("/api/games/clear-status", json={
            "status": "wishlist"
        })
        self.assertEqual(res2.status_code, 200)
        self.assertGreaterEqual(res2.json().get("deleted_count", 0), 1)
        
        # Cleanup
        db.delete_game(g1["id"])
        db.delete_game(g2["id"])
