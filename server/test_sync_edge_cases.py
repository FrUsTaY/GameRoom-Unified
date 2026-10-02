"""
Targeted tests for sync and restore fixes:
1. Full bundle round-trip with metadata preservation and legacy bundle import
2. clear_games_status tombstone generation and delta sync visibility
3. move_games_status updated_at/updated_by propagation to delta sync
4. log_playtime updated_at/updated_by propagation to delta sync
"""
import sys
import os
import time
import json
import unittest
import uuid
from datetime import datetime, timezone, timedelta

app_dir = os.path.dirname(os.path.abspath(__file__))
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)

import database as db
import sync_service
import security
from fastapi.testclient import TestClient
from main import app

class TestSyncEdgeCases(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.test_db_path = os.path.join(app_dir, "test_sync_edge_cases.db")
        if os.path.exists(cls.test_db_path):
            try:
                os.remove(cls.test_db_path)
            except Exception:
                pass
        os.environ["BACKLOG_DB_PATH"] = cls.test_db_path
        db.DB_PATH = cls.test_db_path
        db.init_db()
        cls.client = TestClient(app)
        cls.token = security.get_or_create_sync_token()
        cls.headers = {"Authorization": f"Bearer {cls.token}"}

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.test_db_path):
            try:
                os.remove(cls.test_db_path)
            except Exception:
                pass

    def test_01_full_bundle_roundtrip_preserves_metadata(self):
        """
        Tests that export -> import -> export preserves game identity (UUID)
        and sync metadata (updated_at, updated_by, client_created_at, created_at),
        and that legacy bundles without UUID import correctly with generated UUIDs.
        """
        # 1. Create games with known UUID and sync metadata
        known_uuid_1 = "11111111-2222-3333-4444-555555555555"
        known_uuid_2 = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        t1 = "2026-03-01T10:00:00+00:00"
        t2 = "2026-03-01T12:30:00+00:00"
        
        g1 = db.create_game({
            "uuid": known_uuid_1,
            "title": "Hollow Knight Silksong",
            "status": "backlog",
            "platform": "PC",
            "platforms_list": ["PC", "Nintendo Switch"],
            "genres": "Metroidvania",
            "developer": "Team Cherry",
            "publisher": "Team Cherry",
            "user_playtime_minutes": 150,
            "rating_grade": "izumitelno",
            "user_score": 10,
            "notes": "Must play on launch",
            "created_at": t1,
            "client_created_at": t1,
            "updated_at": t2,
            "updated_by": "custom-tester"
        })
        
        g2 = db.create_game({
            "uuid": known_uuid_2,
            "title": "Elden Ring Shadow of the Erdtree",
            "status": "completed",
            "platform": "PC",
            "platforms_list": ["PC"],
            "genres": "Action RPG",
            "developer": "FromSoftware",
            "publisher": "Bandai Namco",
            "user_playtime_minutes": 3600,
            "rating_grade": "izumitelno",
            "user_score": 10,
            "notes": "Masterpiece DLC",
            "created_at": t1,
            "client_created_at": t1,
            "updated_at": t2,
            "updated_by": "custom-tester-2"
        })

        self.assertEqual(g1["uuid"], known_uuid_1)
        self.assertEqual(g2["uuid"], known_uuid_2)
        self.assertEqual(g1["updated_at"], t2)
        self.assertEqual(g1["updated_by"], "custom-tester")
        self.assertEqual(g1["client_created_at"], t1)

        # 2. Export full bundle
        bundle = db.export_full_database_json()
        self.assertIn("games", bundle)
        exported_uuids = {g["uuid"] for g in bundle["games"]}
        self.assertIn(known_uuid_1, exported_uuids)
        self.assertIn(known_uuid_2, exported_uuids)

        # 3. Simulate clean database import: clear games table in test DB and re-import
        conn = db.get_db_connection()
        conn.cursor().execute("DELETE FROM games")
        conn.cursor().execute("DELETE FROM play_sessions")
        conn.commit()
        
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM games")
        count_before = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(count_before, 0, "Games table should be empty before import")

        import_res = db.import_full_database_json(bundle)
        self.assertTrue(import_res["success"])
        self.assertGreaterEqual(import_res["imported_games"], 2)

        # 4. Check that UUID of each game matches
        imported_g1 = db.get_game_by_uuid(known_uuid_1)
        imported_g2 = db.get_game_by_uuid(known_uuid_2)

        self.assertIsNotNone(imported_g1, "Game 1 should be restored by original UUID")
        self.assertIsNotNone(imported_g2, "Game 2 should be restored by original UUID")

        # 5. Check updated_at, updated_by, client_created_at, and created_at
        self.assertEqual(imported_g1["uuid"], known_uuid_1)
        self.assertEqual(imported_g1["updated_at"], t2)
        self.assertEqual(imported_g1["updated_by"], "custom-tester")
        self.assertEqual(imported_g1["client_created_at"], t1)
        self.assertEqual(imported_g1["created_at"], t1)

        self.assertEqual(imported_g2["uuid"], known_uuid_2)
        self.assertEqual(imported_g2["updated_at"], t2)
        self.assertEqual(imported_g2["updated_by"], "custom-tester-2")
        self.assertEqual(imported_g2["client_created_at"], t1)
        self.assertEqual(imported_g2["created_at"], t1)

        # 6. Check that game data is intact
        self.assertEqual(imported_g1["title"], "Hollow Knight Silksong")
        self.assertEqual(imported_g1["user_playtime_minutes"], 150)
        self.assertEqual(imported_g1["developer"], "Team Cherry")
        self.assertEqual(imported_g1["rating_grade"], "izumitelno")
        self.assertEqual(imported_g2["title"], "Elden Ring Shadow of the Erdtree")
        self.assertEqual(imported_g2["user_playtime_minutes"], 3600)

        # Round-trip export: verify second export matches restored metadata
        bundle2 = db.export_full_database_json()
        b2_map = {g["uuid"]: g for g in bundle2["games"]}
        self.assertEqual(b2_map[known_uuid_1]["updated_at"], t2)
        self.assertEqual(b2_map[known_uuid_1]["updated_by"], "custom-tester")
        self.assertEqual(b2_map[known_uuid_2]["updated_at"], t2)
        self.assertEqual(b2_map[known_uuid_2]["updated_by"], "custom-tester-2")

        # 7. Legacy bundle without UUID: must import and generate UUID
        legacy_bundle = {
            "version": "1.0.0",
            "games": [
                {
                    "title": "Legacy Retro Game",
                    "status": "backlog",
                    "platform": "PC",
                    "created_at": "2025-01-01T00:00:00"
                }
            ]
        }
        legacy_import_res = db.import_full_database_json(legacy_bundle)
        self.assertTrue(legacy_import_res["success"])
        
        conn = db.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM games WHERE title = 'Legacy Retro Game'")
        row = cursor.fetchone()
        conn.close()
        self.assertIsNotNone(row, "Legacy game without UUID must be imported")
        legacy_game = dict(row)
        self.assertTrue(bool(legacy_game["uuid"]), "Legacy game must receive a valid generated UUID")
        self.assertTrue(bool(legacy_game["updated_at"]), "Legacy game must have updated_at populated")
        self.assertEqual(legacy_game["updated_by"], "web-admin")

    def test_02_clear_games_status_creates_tombstones_and_visible_in_delta_sync(self):
        """
        Tests that clear_games_status creates sync tombstones for all cleared games,
        deletes them from games table, and delta sync returns the tombstones.
        """
        # 1. Create multiple games with status 'paused'
        g1 = db.create_game({"title": "ClearStatusGame1", "status": "paused"})
        g2 = db.create_game({"title": "ClearStatusGame2", "status": "paused"})
        g_other = db.create_game({"title": "KeepGame", "status": "playing"})
        
        uuid1 = g1["uuid"]
        uuid2 = g2["uuid"]
        other_uuid = g_other["uuid"]

        since = (datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat()
        time.sleep(0.05)

        # 2. Execute clear_games_status for 'paused'
        deleted_count = db.clear_games_status("paused")
        self.assertEqual(deleted_count, 2)

        # 3. Verify games disappeared from games table
        self.assertIsNone(db.get_game_by_uuid(uuid1))
        self.assertIsNone(db.get_game_by_uuid(uuid2))
        self.assertIsNotNone(db.get_game_by_uuid(other_uuid), "Unrelated game must not be deleted")

        # 4. Verify tombstones exist in sync_tombstones
        conn = db.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT uuid, deleted_at, deleted_by, title_backup FROM sync_tombstones WHERE uuid IN (?, ?)", (uuid1, uuid2))
        tombstones = {r["uuid"]: dict(r) for r in cursor.fetchall()}
        conn.close()

        self.assertIn(uuid1, tombstones)
        self.assertIn(uuid2, tombstones)
        self.assertEqual(tombstones[uuid1]["title_backup"], "ClearStatusGame1")
        self.assertEqual(tombstones[uuid1]["deleted_by"], "web-admin")
        self.assertEqual(tombstones[uuid2]["title_backup"], "ClearStatusGame2")
        self.assertEqual(tombstones[uuid2]["deleted_by"], "web-admin")

        # 5. Verify delta sync sees these tombstones
        sync_payload = {
            "client_id": "test-android-device-clear",
            "client_version": "1.0",
            "client_time_now": datetime.now(timezone.utc).isoformat(),
            "last_sync_timestamp": since,
            "changes": {"created": [], "updated": [], "deleted": []}
        }
        res = self.client.post("/api/sync", json=sync_payload, headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()

        deleted_in_sync = {d["uuid"] for d in data["server_changes"]["deleted"]}
        self.assertIn(uuid1, deleted_in_sync, "Delta sync must contain tombstone for cleared game 1")
        self.assertIn(uuid2, deleted_in_sync, "Delta sync must contain tombstone for cleared game 2")

    def test_03_move_games_status_updates_metadata_and_propagates_to_delta_sync(self):
        """
        Tests that move_games_status updates status, updated_at, updated_by,
        preserves UUID, does not create tombstones, and delta sync returns the moved games.
        """
        # 1. Create a game with an older updated_at
        old_time = "2026-01-01T00:00:00+00:00"
        g = db.create_game({
            "title": "MoveStatusTestGame",
            "status": "wishlist",
            "updated_at": old_time,
            "updated_by": "initial-actor"
        })
        game_uuid = g["uuid"]
        self.assertEqual(g["updated_at"], old_time)

        since = (datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat()
        time.sleep(0.05)

        # 2. Execute move_games_status
        moved_count = db.move_games_status("wishlist", "backlog")
        self.assertGreaterEqual(moved_count, 1)

        # 3. Verify game was updated
        updated_g = db.get_game_by_uuid(game_uuid)
        self.assertIsNotNone(updated_g)
        self.assertEqual(updated_g["status"], "backlog")
        self.assertNotEqual(updated_g["updated_at"], old_time, "updated_at must change after move_games_status")
        self.assertGreater(updated_g["updated_at"], since)
        self.assertEqual(updated_g["updated_by"], "web-admin", "updated_by must be set to web-admin")
        self.assertEqual(updated_g["uuid"], game_uuid, "UUID must remain unchanged")

        # 4. Verify no tombstone was created
        conn = db.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sync_tombstones WHERE uuid = ?", (game_uuid,))
        self.assertIsNone(cursor.fetchone(), "No tombstone should be created for moved games")
        conn.close()

        # 5. Verify delta sync receives the moved game
        sync_payload = {
            "client_id": "test-android-device-move",
            "client_version": "1.0",
            "client_time_now": datetime.now(timezone.utc).isoformat(),
            "last_sync_timestamp": since,
            "changes": {"created": [], "updated": [], "deleted": []}
        }
        res = self.client.post("/api/sync", json=sync_payload, headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()

        updated_in_sync = {u["uuid"]: u for u in data["server_changes"]["updated"]}
        self.assertIn(game_uuid, updated_in_sync, "Delta sync must return the game whose status was moved")
        self.assertEqual(updated_in_sync[game_uuid]["status"], "backlog")

    def test_04_log_playtime_updates_metadata_and_propagates_to_delta_sync(self):
        """
        Tests that log_playtime updates user_playtime_minutes, last_played_at,
        updated_at, and updated_by, adds a play_sessions entry, and delta sync returns the game.
        """
        # 1. Create a game with initial playtime and old updated_at
        old_time = "2026-01-01T00:00:00+00:00"
        g = db.create_game({
            "title": "PlaytimeTestGame",
            "status": "playing",
            "user_playtime_minutes": 60,
            "updated_at": old_time,
            "updated_by": "initial-actor"
        })
        game_id = g["id"]
        game_uuid = g["uuid"]

        since = (datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat()
        time.sleep(0.05)

        # 2. Call log_playtime via database method (or quick-time endpoint)
        updated_g = db.log_playtime(game_id, 45, note="Boss battle session")
        self.assertIsNotNone(updated_g)

        # 3. Check playtime changed
        self.assertEqual(updated_g["user_playtime_minutes"], 105)
        self.assertTrue(bool(updated_g["last_played_at"]))
        self.assertGreater(updated_g["last_played_at"], since)

        # 4. Check updated_at changed
        self.assertNotEqual(updated_g["updated_at"], old_time, "updated_at must change after log_playtime")
        self.assertGreater(updated_g["updated_at"], since)

        # 5. Check updated_by is web-admin
        self.assertEqual(updated_g["updated_by"], "web-admin")

        # 6. Check play_sessions entry was created
        conn = db.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM play_sessions WHERE game_id = ? ORDER BY id DESC LIMIT 1", (game_id,))
        session = cursor.fetchone()
        self.assertIsNotNone(session)
        self.assertEqual(session["duration_minutes"], 45)
        self.assertEqual(session["note"], "Boss battle session")
        conn.close()

        # 7. Check delta sync receives the game with updated playtime
        sync_payload = {
            "client_id": "test-android-device-playtime",
            "client_version": "1.0",
            "client_time_now": datetime.now(timezone.utc).isoformat(),
            "last_sync_timestamp": since,
            "changes": {"created": [], "updated": [], "deleted": []}
        }
        res = self.client.post("/api/sync", json=sync_payload, headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()

        updated_in_sync = {u["uuid"]: u for u in data["server_changes"]["updated"]}
        self.assertIn(game_uuid, updated_in_sync, "Delta sync must return the game after playtime update")
        self.assertEqual(updated_in_sync[game_uuid]["user_playtime_minutes"], 105)

    def test_rating_change_10_to_3_sync(self):
        """Item 1: Verify rating change from 10/10 to 3/10 updates rating_grade to musor on Web"""
        game_uuid = str(uuid.uuid4())
        initial_game = db.create_game({
            "uuid": game_uuid,
            "title": "Rating Conversion Test Game",
            "status": "completed",
            "platform": "PC",
            "user_score": 10,
            "rating_grade": "izumitelno"
        })
        self.assertEqual(initial_game["rating_grade"], "izumitelno")
        self.assertEqual(initial_game["user_score"], 10)

        # Android sends delta update with score 3 and rating_grade musor
        now_str = datetime.now(timezone.utc).isoformat()
        sync_payload = {
            "client_id": "test-android-rating-client",
            "client_version": "1.0",
            "client_time_now": now_str,
            "last_sync_timestamp": now_str,
            "changes": {
                "created": [],
                "updated": [{
                    "uuid": game_uuid,
                    "title": "Rating Conversion Test Game",
                    "status": "completed",
                    "platform": "PC",
                    "user_score": 3,
                    "rating_grade": "musor",
                    "updated_at": now_str
                }],
                "deleted": []
            }
        }
        res = self.client.post("/api/sync", json=sync_payload, headers=self.headers)
        self.assertEqual(res.status_code, 200)

        # Check server DB and Web API
        updated_game = db.get_game_by_uuid(game_uuid)
        self.assertEqual(updated_game["user_score"], 3)
        self.assertEqual(updated_game["rating_grade"], "musor")

        # Also test if Android sends only user_score 3 without rating_grade, server parses it to musor
        game_uuid2 = str(uuid.uuid4())
        db.create_game({
            "uuid": game_uuid2,
            "title": "Rating Conversion Test Game 2",
            "status": "completed",
            "platform": "PC",
            "user_score": 10,
            "rating_grade": "izumitelno"
        })
        sync_payload2 = {
            "client_id": "test-android-rating-client",
            "client_version": "1.0",
            "client_time_now": now_str,
            "last_sync_timestamp": now_str,
            "changes": {
                "created": [],
                "updated": [{
                    "uuid": game_uuid2,
                    "title": "Rating Conversion Test Game 2",
                    "status": "completed",
                    "platform": "PC",
                    "user_score": 3,
                    "rating_grade": "",
                    "updated_at": now_str
                }],
                "deleted": []
            }
        }
        res2 = self.client.post("/api/sync", json=sync_payload2, headers=self.headers)
        self.assertEqual(res2.status_code, 200)

        updated_game2 = db.get_game_by_uuid(game_uuid2)
        self.assertEqual(updated_game2["user_score"], 3)
        self.assertEqual(updated_game2["rating_grade"], "musor")

    def test_wishlist_avg_playtime_sync(self):
        """Item 2: Verify Wishlist avgPlaytime update propagates to server playtime_main"""
        wish_uuid = str(uuid.uuid4())
        initial_wish = db.create_game({
            "uuid": wish_uuid,
            "title": "Wishlist Playtime Game",
            "status": "backlog",
            "platform": "PC",
            "playtime_main": 0.0
        })
        self.assertEqual(initial_wish["playtime_main"], 0.0)

        now_str = datetime.now(timezone.utc).isoformat()
        sync_payload = {
            "client_id": "test-android-wishlist-client",
            "client_version": "1.0",
            "client_time_now": now_str,
            "last_sync_timestamp": now_str,
            "changes": {
                "created": [],
                "updated": [{
                    "uuid": wish_uuid,
                    "title": "Wishlist Playtime Game",
                    "status": "backlog",
                    "platform": "PC",
                    "playtime_main": 18.5,
                    "updated_at": now_str
                }],
                "deleted": []
            }
        }
        res = self.client.post("/api/sync", json=sync_payload, headers=self.headers)
        self.assertEqual(res.status_code, 200)

        updated_wish = db.get_game_by_uuid(wish_uuid)
        self.assertEqual(updated_wish["playtime_main"], 18.5)

    def test_07_bidirectional_rating_synchronization(self):
        """Verify rating_grade and user_score are automatically synchronized in db and sync"""
        test_uuid = str(uuid.uuid4())
        # 1. Create with rating_grade only -> user_score is calculated
        game1 = db.create_game({
            "uuid": test_uuid,
            "title": "Rating Sync Test Game",
            "status": "completed",
            "rating_grade": "izumitelno"
        })
        self.assertEqual(game1["rating_grade"], "izumitelno")
        self.assertEqual(game1["user_score"], 10)

        # 2. Update with rating_grade = 'pohvalno' -> user_score becomes 8
        game2 = db.update_game(game1["id"], {"rating_grade": "pohvalno"})
        self.assertEqual(game2["rating_grade"], "pohvalno")
        self.assertEqual(game2["user_score"], 8)

        # 3. Update with rating_grade = 'musor' -> user_score becomes 3
        game3 = db.update_game(game1["id"], {"rating_grade": "musor"})
        self.assertEqual(game3["rating_grade"], "musor")
        self.assertEqual(game3["user_score"], 3)

        # 4. Update with rating_grade = '' -> user_score becomes 0
        game4 = db.update_game(game1["id"], {"rating_grade": ""})
        self.assertEqual(game4["rating_grade"], "")
        self.assertEqual(game4["user_score"], 0)

        # 5. Update with user_score = 6 (via Android score) -> rating_grade becomes 'prohodnyak'
        game5 = db.update_game(game1["id"], {"user_score": 6})
        self.assertEqual(game5["rating_grade"], "prohodnyak")
        self.assertEqual(game5["user_score"], 6)

        # 6. Delta sync client receiving server updated rating_grade
        sync_client_now = datetime.now(timezone.utc).isoformat()
        db.update_game(game1["id"], {"rating_grade": "pohvalno", "updated_by": "web-admin"})
        res = self.client.post("/api/sync", json={
            "client_id": "test-device-rating-sync",
            "client_version": "1.0",
            "client_time_now": sync_client_now,
            "last_sync_timestamp": "2020-01-01T00:00:00+00:00",
            "changes": {"created": [], "updated": [], "deleted": []}
        }, headers=self.headers)
        self.assertEqual(res.status_code, 200)
        changes = res.json()["server_changes"]["updated"]
        synced_game = next((g for g in changes if g["uuid"] == test_uuid), None)
        self.assertIsNotNone(synced_game)
        self.assertEqual(synced_game["rating_grade"], "pohvalno")
        self.assertEqual(synced_game["user_score"], 8)

    def test_08_bidirectional_rating_and_month_sync_no_false_conflict(self):
        """
        Tests true bidirectional sync:
        - Android modifies game from 10/10 to 5/10 and changes month from 10.2026 to 09.2026
        - Server delta sync applies update directly without false conflict reversion
        - Web subsequently modifies rating to 'izumitelno'
        - Android delta sync receives the web modification cleanly
        """
        test_uuid = str(uuid.uuid4())
        initial_sync_time = "2026-10-02T01:00:00+00:00"

        # 1. Game on server initially set via Web to izumitelno (score 10) and month 10.2026
        g = db.create_game({
            "uuid": test_uuid,
            "title": "Bidi Sync Test Game",
            "status": "completed",
            "rating_grade": "izumitelno",
            "user_score": 10,
            "completed_at": "10.2026",
            "updated_at": initial_sync_time,
            "updated_by": "web-admin"
        })

        client_id = "android-client-test-bidi"

        # 2. Android client made a local change: score 5/10 -> user_score: 5, rating_grade: prohodnyak, completed_at: 09.2026
        client_edit_time = "2026-10-02T01:05:00+00:00"
        client_sync_time = "2026-10-02T01:05:05+00:00"

        res = self.client.post("/api/sync", json={
            "client_id": client_id,
            "client_version": "1.0",
            "client_time_now": client_sync_time,
            "last_sync_timestamp": initial_sync_time,
            "changes": {
                "created": [],
                "updated": [{
                    "uuid": test_uuid,
                    "title": "Bidi Sync Test Game",
                    "status": "completed",
                    "rating_grade": "prohodnyak",
                    "user_score": 5,
                    "completed_at": "09.2026",
                    "updated_at": client_edit_time
                }],
                "deleted": []
            }
        }, headers=self.headers)

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertIn(test_uuid, data["ack"]["applied_updated"])
        # Crucial: Must NOT be returned in server_changes.updated as a winning conflict!
        updated_in_server_changes = [x for x in data["server_changes"]["updated"] if x["uuid"] == test_uuid]
        self.assertEqual(len(updated_in_server_changes), 0, "Client update must not trigger false server-wins conflict")

        # Verify DB is updated with client's new score and month
        db_game = db.get_game_by_uuid(test_uuid)
        self.assertEqual(db_game["rating_grade"], "prohodnyak")
        self.assertEqual(db_game["user_score"], 5)
        self.assertEqual(db_game["completed_at"], "09.2026")

        # 3. Web changes rating from prohodnyak to izumitelno
        server_sync_time_1 = data["server_time"]
        db.update_game(g["id"], {
            "rating_grade": "izumitelno",
            "user_score": 10,
            "updated_by": "web-admin"
        })

        # 4. Android syncs again
        res2 = self.client.post("/api/sync", json={
            "client_id": client_id,
            "client_version": "1.0",
            "client_time_now": datetime.now(timezone.utc).isoformat(),
            "last_sync_timestamp": server_sync_time_1,
            "changes": {"created": [], "updated": [], "deleted": []}
        }, headers=self.headers)
        self.assertEqual(res2.status_code, 200)
        data2 = res2.json()
        changes2 = data2["server_changes"]["updated"]
        synced_game2 = next((x for x in changes2 if x["uuid"] == test_uuid), None)
        self.assertIsNotNone(synced_game2)
        self.assertEqual(synced_game2["rating_grade"], "izumitelno")
        self.assertEqual(synced_game2["user_score"], 10)
        self.assertEqual(synced_game2["completed_at"], "09.2026")

if __name__ == "__main__":
    unittest.main()
