import subprocess
import time
import os
import sys
from playwright.sync_api import sync_playwright

def start_server():
    print("Starting server...")
    env = os.environ.copy()
    env["GAME_ROOM_WEB_USERNAME"] = "admin"
    env["GAME_ROOM_WEB_PASSWORD_HASH"] = "$argon2id$v=19$m=65536,t=3,p=4$JtuAkpX3NMzZ3VlRd9ahKg$KESWQ9rrTsB7+4cUm1ErPYcC2MOtq59zJSTxg3ew0UQ"
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"],
        cwd="/app/server",
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

def run_cuj(page):
    print("Running CUJ...")
    page.goto("http://localhost:8080")
    page.wait_for_timeout(2000)

    if page.locator("input[placeholder='admin']").is_visible(timeout=1000) or page.locator("input[type='password']").is_visible(timeout=1000):
        print("Logging in...")
        inputs = page.locator("input")
        inputs.nth(0).fill("admin")
        inputs.nth(1).fill("dummy")
        page.get_by_role("button").click()
        page.wait_for_timeout(2000)

    print("Clicking Backlog tab...")
    # It might be in the sidebar or an icon
    try:
        page.locator("a[data-tab='backlog']").click(timeout=5000)
    except:
        print("Failed to click via locator")

    page.wait_for_timeout(2000)

    print("Taking screenshot...")
    page.screenshot(path="/home/jules/verification/screenshots/verification.png")
    page.wait_for_timeout(1000)

if __name__ == "__main__":
    os.makedirs("/home/jules/verification/videos", exist_ok=True)
    os.makedirs("/home/jules/verification/screenshots", exist_ok=True)

    server = start_server()
    time.sleep(4) # Wait for startup

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                record_video_dir="/home/jules/verification/videos",
                viewport={'width': 1280, 'height': 720}
            )
            page = context.new_page()
            try:
                run_cuj(page)
            finally:
                context.close()
                browser.close()
    finally:
        server.terminate()
        server.wait()
