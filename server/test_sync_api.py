"""
Automated Test Suite for Distributed Sync Engine & Sync API
Tests Authentication, Database Auto-Migrations, Delta-Sync, Tombstones,
Clock-Skew Time Resolution, RAWG Protection, and Initial Sync Merge.
"""
import sys
import os
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

class TestSyncAPI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        test_db_path = os.path.join(app_dir, "test_sync_backlog.db")
        if os.path.exists(test_db_path):
            os.remove(test_db_path)
        os.environ["BACKLOG_DB_PATH"] = test_db_path
        db.DB_PATH = test_db_path
        db.init_db()
        cls.client = TestClient(app)
        cls.token = security.get_or_create_sync_token()
        cls.headers = {"Authorization": f"Bearer {cls.token}"}

    @classmethod
    def tearDownClass(cls):
        test_db_path = os.path.join(app_dir, "test_sync_backlog.db")
        if os.path.exists(test_db_path):
            try:
                os.remove(test_db_path)
            except Exception:
                pass

    def test_01_db_migration_and_uuids(self):
        """Verifies games have UUIDs, sync_tombstones table exists, and token is saved."""
        games = db.get_games()
        self.assertGreaterEqual(len(games), 1, "Games table should have seeded entries")
        for g in games:
            self.assertTrue(bool(g.get("uuid")), f"Game {g.get('title')} must have a valid UUID")
            self.assertTrue(bool(g.get("updated_at")), f"Game {g.get('title')} must have updated_at")

        conn = db.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sync_tombstones'")
        self.assertIsNotNone(cursor.fetchone(), "sync_tombstones table must exist")
        conn.close()

    def test_02_auth_protection(self):
        """Verifies endpoints reject unauthorized requests and accept valid Bearer tokens."""
        # Unauthorized without token
        res_no_auth = self.client.get("/api/sync/status")
        self.assertEqual(res_no_auth.status_code, 401)

        # Unauthorized with bad token
        res_bad_auth = self.client.get("/api/sync/status", headers={"Authorization": "Bearer bad-token-123"})
        self.assertEqual(res_bad_auth.status_code, 401)

        # Authorized
        res_auth = self.client.get("/api/sync/status", headers=self.headers)
        self.assertEqual(res_auth.status_code, 200)
        data = res_auth.json()
        self.assertEqual(data["status"], "online")
        self.assertIn("total_games", data)

    def test_03_delta_sync_create_and_update(self):
        """Verifies creating and updating a game via delta-sync."""
        game_uuid = str(uuid.uuid4())
        client_now = datetime.now(timezone.utc).isoformat()

        sync_payload = {
            "client_id": "test-device-1",
            "client_version": "1.0",
            "client_time_now": client_now,
            "last_sync_timestamp": "",
            "changes": {
                "created": [
                    {
                        "uuid": game_uuid,
                        "client_seq": 1,
                        "title": "Celeste Chapter 9",
                        "status": "playing",
                        "platform": "PC",
                        "user_playtime_minutes": 120,
                        "playtime_main": 8.0,
                        "rating_grade": "",
                        "user_score": 0,
                        "notes": "Farewell DLC",
                        "created_at": client_now,
                        "updated_at": client_now
                    }
                ],
                "updated": [],
                "deleted": []
            }
        }

        res = self.client.post("/api/sync", json=sync_payload, headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertIn(game_uuid, data["ack"]["applied_created"])

        # Check record in DB
        db_game = db.get_game_by_uuid(game_uuid)
        self.assertIsNotNone(db_game)
        self.assertEqual(db_game["title"], "Celeste Chapter 9")
        self.assertEqual(db_game["status"], "playing")
        self.assertEqual(db_game["user_playtime_minutes"], 120)

        # Now test updating playtime and status (e.g. typo fix 120 -> 90 minutes)
        update_time = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
        update_payload = {
            "client_id": "test-device-1",
            "client_version": "1.0",
            "client_time_now": update_time,
            "last_sync_timestamp": data["server_time"],
            "changes": {
                "created": [],
                "updated": [
                    {
                        "uuid": game_uuid,
                        "client_seq": 2,
                        "title": "Celeste Chapter 9",
                        "status": "completed",
                        "platform": "PC",
                        "user_playtime_minutes": 90,  # Reduced time (typo fix test)
                        "rating_grade": "izumitelno",
                        "user_score": 10,
                        "notes": "Farewell DLC finished!",
                        "completed_at": update_time,
                        "updated_at": update_time
                    }
                ],
                "deleted": []
            }
        }

        res2 = self.client.post("/api/sync", json=update_payload, headers=self.headers)
        self.assertEqual(res2.status_code, 200)
        data2 = res2.json()
        self.assertIn(game_uuid, data2["ack"]["applied_updated"])

        # Verify in DB: time was reduced to 90 min (LWW works, not blocked by max)
        updated_game = db.get_game_by_uuid(game_uuid)
        self.assertEqual(updated_game["status"], "completed")
        self.assertEqual(updated_game["user_playtime_minutes"], 90)
        self.assertEqual(updated_game["rating_grade"], "izumitelno")
        self.assertEqual(updated_game["user_score"], 10)

    def test_04_tombstone_deletion(self):
        """Verifies deleted game is removed and logged in sync_tombstones."""
        del_uuid = str(uuid.uuid4())
        now_str = datetime.now(timezone.utc).isoformat()

        # First create a game
        db.create_game({
            "uuid": del_uuid,
            "title": "Game to Delete",
            "status": "backlog",
            "platform": "PC"
        })
        self.assertIsNotNone(db.get_game_by_uuid(del_uuid))

        # Send delete via sync
        del_payload = {
            "client_id": "test-device-1",
            "client_time_now": now_str,
            "last_sync_timestamp": now_str,
            "changes": {
                "created": [],
                "updated": [],
                "deleted": [
                    {
                        "uuid": del_uuid,
                        "deleted_at": now_str,
                        "client_seq": 1
                    }
                ]
            }
        }

        res = self.client.post("/api/sync", json=del_payload, headers=self.headers)
        self.assertEqual(res.status_code, 200)
        self.assertIn(del_uuid, res.json()["ack"]["applied_deleted"])

        # Check game is gone from games table
        self.assertIsNone(db.get_game_by_uuid(del_uuid))

        # Check tombstone exists
        conn = db.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT uuid, title_backup FROM sync_tombstones WHERE uuid = ?", (del_uuid,))
        tombstone = cursor.fetchone()
        conn.close()
        self.assertIsNotNone(tombstone)
        self.assertEqual(tombstone["uuid"], del_uuid)

    def test_05_protection_of_server_enriched_fields(self):
        """Verifies that client updating user fields does not erase server RAWG/genres metadata."""
        enrich_uuid = str(uuid.uuid4())
        now_str = datetime.now(timezone.utc).isoformat()

        # Seed game with rich server metadata
        db.create_game({
            "uuid": enrich_uuid,
            "title": "Elden Ring",
            "status": "backlog",
            "platform": "PC",
            "genres": "Экшен, RPG, Открытый мир",
            "developer": "FromSoftware",
            "publisher": "Bandai Namco",
            "rawg_rating": 4.8,
            "metacritic": 96,
            "background_url": "https://media.rawg.io/bg.jpg"
        })

        # Client sends update without genres or developer
        sync_payload = {
            "client_id": "test-device-1",
            "client_time_now": now_str,
            "last_sync_timestamp": "",
            "changes": {
                "created": [],
                "updated": [
                    {
                        "uuid": enrich_uuid,
                        "title": "Elden Ring",
                        "status": "playing",
                        "platform": "PC",
                        "user_playtime_minutes": 60,
                        "notes": "Starting new run",
                        "updated_at": now_str,
                        # Note: genres, developer, publisher, metacritic NOT sent (empty/omitted)
                    }
                ],
                "deleted": []
            }
        }

        res = self.client.post("/api/sync", json=sync_payload, headers=self.headers)
        self.assertEqual(res.status_code, 200)

        # Check that server enriched fields were NOT wiped out
        g = db.get_game_by_uuid(enrich_uuid)
        self.assertEqual(g["status"], "playing")
        self.assertEqual(g["notes"], "Starting new run")
        self.assertEqual(g["genres"], "Экшен, RPG, Открытый мир", "Genres must be preserved")
        self.assertEqual(g["developer"], "FromSoftware", "Developer must be preserved")
        self.assertEqual(g["metacritic"], 96, "Metacritic score must be preserved")

    def test_06_initial_sync_safe_merge(self):
        """Verifies Initial Sync: matching games are merged, non-matching games are kept separate."""
        # Existing game in server DB: "Death Stranding 2: On the Beach" (rawg_id 892556)
        initial_payload = {
            "client_id": "android-phone-initial",
            "client_time_now": datetime.now(timezone.utc).isoformat(),
            "games": [
                {
                    "title": "Death Stranding 2: On the Beach",
                    "rawg_id": 892556,
                    "platform": "Домашний ПК",
                    "time": "5.0",
                    "note": "Preordered on PC",
                    "status": "В процессе"
                },
                {
                    "title": "Brand New Indie Game",
                    "platform": "Nintendo Switch",
                    "time": "2.0",
                    "note": "Unique game only on phone",
                    "status": "В процессе"
                }
            ],
            "wishlist": [
                {
                    "title": "Silksong",
                    "platform": "Домашний ПК",
                    "expectedYear": "2026",
                    "note": "Waiting patiently"
                }
            ]
        }

        res = self.client.post("/api/sync/initial", json=initial_payload, headers=self.headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertGreaterEqual(data["merged_count"], 1, "Death Stranding 2 should be merged")
        self.assertGreaterEqual(data["created_count"], 2, "Indie game and Silksong should be created")

        # Verify that Silksong was created with status 'wishlist'
        silksong = next((g for g in data["games"] if "Silksong" in g["title"]), None)
        self.assertIsNotNone(silksong)
        self.assertEqual(silksong["status"], "wishlist")

        # Verify Indie Game created on Switch
        indie = next((g for g in data["games"] if "Brand New Indie Game" in g["title"]), None)
        self.assertIsNotNone(indie)
        self.assertEqual(indie["platform"], "Nintendo Switch")

if __name__ == "__main__":
    unittest.main()
