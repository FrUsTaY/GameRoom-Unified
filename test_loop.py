import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Create context to intercept requests
        context = await browser.new_context()
        page = await context.new_page()

        requests_log = []

        page.on("request", lambda request: requests_log.append({"url": request.url, "method": request.method, "resource_type": request.resource_type}))
        page.on("response", lambda response: requests_log.append({"type": "response", "url": response.url, "status": response.status}))

        print("Navigating to /login...")
        await page.goto("http://localhost:8080/login")

        print("Filling form...")
        await page.fill("#username", "FrUsTaY")
        await page.fill("#password", "test") # password doesn't matter much for our mocked hash

        print("Clicking login...")
        await page.click("#login-submit-btn")

        print("Waiting 2 seconds to let the loop spin...")
        await asyncio.sleep(2)

        print("\n--- Network Log ---")
        for log in requests_log:
            if "type" in log and log["type"] == "response":
                print(f"RES: {log['status']} {log['url']}")
            else:
                print(f"REQ: {log['method']} {log['url']} ({log['resource_type']})")

        print("\n--- Executing tests on current page ---")

        # Now run the test fetch commands
        # 1. without credentials
        try:
            res1_status, res1_text = await page.evaluate("""
                async () => {
                    try {
                        const r = await fetch('/api/auth/me');
                        const text = await r.text();
                        return [r.status, text];
                    } catch (e) {
                        return ['error', e.toString()];
                    }
                }
            """)
            print(f"fetch('/api/auth/me') (without include) -> Status: {res1_status}, Body: {res1_text}")
        except Exception as e:
            print(f"Error executing fetch1: {e}")

        # 2. with credentials: 'include'
        try:
            res2_status, res2_text = await page.evaluate("""
                async () => {
                    try {
                        const r = await fetch('/api/auth/me', {credentials: 'include'});
                        const text = await r.text();
                        return [r.status, text];
                    } catch (e) {
                        return ['error', e.toString()];
                    }
                }
            """)
            print(f"fetch('/api/auth/me', {{credentials:'include'}}) -> Status: {res2_status}, Body: {res2_text}")
        except Exception as e:
            print(f"Error executing fetch2: {e}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
