# run_e2e_integration_tests.py
# Python orchestrator for real end-to-end integration tests

import os
import sys
import time
import tempfile
import subprocess
import urllib.request
import json

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

PORT = 8099
SERVER_URL = f"http://127.0.0.1:{PORT}"

def main():
    print("=====================================================")
    print("  Orchestrating Real End-to-End Integration Tests")
    print("=====================================================")

    # 1. Prepare isolated temporary database
    temp_dir = tempfile.mkdtemp(prefix="gameroom_e2e_")
    test_db_path = os.path.join(temp_dir, "test_e2e.db")
    print(f"📁 Isolated Test DB: {test_db_path}")

    # Set environment variables for server process
    import secrets
    from argon2 import PasswordHasher
    test_sync_token = "e2e_sync_token_" + secrets.token_hex(16)
    test_pass_hash = PasswordHasher().hash("e2e_test_password")

    env = os.environ.copy()
    env["BACKLOG_DB_PATH"] = test_db_path
    env["PYTHONUNBUFFERED"] = "1"
    env["GAMEROOM_SYNC_TOKEN"] = test_sync_token
    env["GAME_ROOM_WEB_USERNAME"] = "e2e_admin"
    env["GAME_ROOM_WEB_PASSWORD_HASH"] = test_pass_hash

    server_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server")

    # 2. Launch FastAPI / Uvicorn server subprocess
    cmd = [
        sys.executable, "-m", "uvicorn", "main:app",
        "--host", "127.0.0.1",
        "--port", str(PORT),
        "--log-level", "warning"
    ]
    print(f"🚀 Starting FastAPI server on port {PORT}...")
    server_proc = subprocess.Popen(cmd, cwd=server_dir, env=env)

    try:
        # 3. Wait for server to become healthy
        print("⏳ Waiting for server healthcheck...")
        healthy = False
        for _ in range(30):
            try:
                with urllib.request.urlopen(f"{SERVER_URL}/api/health", timeout=1) as resp:
                    if resp.status == 200:
                        healthy = True
                        break
            except Exception:
                time.sleep(0.3)

        if not healthy:
            print("❌ Server failed to start within 10 seconds.")
            server_proc.kill()
            sys.exit(1)

        print("✅ Server is online and responding!")

        # 4. Use the configured Sync Token
        sync_token = test_sync_token
        print(f"🔑 Using Sync Token: {sync_token[:8]}...")

        # 5. Run the Node.js Real Android Sync Test Runner
        js_test_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_real_android_sync.js")
        print("\n⚡ Launching Node.js Android Sync Engine against real server...\n")
        
        node_cmd = ["node", js_test_path, SERVER_URL, sync_token]
        res = subprocess.run(node_cmd, cwd=os.path.dirname(os.path.abspath(__file__)))
        
        if res.returncode != 0:
            print(f"\n❌ Integration tests failed with return code {res.returncode}")
            sys.exit(res.returncode)

        print("\n🎯 ALL INTEGRATION TEST SUITES PASSED PERFECTLY!")

    finally:
        # Clean shutdown
        print("🛑 Terminating test server...")
        server_proc.terminate()
        try:
            server_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            server_proc.kill()
        
        # Clean up temp db
        try:
            if os.path.exists(test_db_path):
                os.remove(test_db_path)
            os.rmdir(temp_dir)
        except Exception:
            pass

if __name__ == "__main__":
    main()
