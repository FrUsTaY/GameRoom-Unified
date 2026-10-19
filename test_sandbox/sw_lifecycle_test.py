"""Browser-level verification of the GameRoom Service Worker cache lifecycle."""
from playwright.sync_api import sync_playwright

EXEC = '/root/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome'
BASE = 'http://127.0.0.1:8080'
ok = []

def check(name, cond):
    ok.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path=EXEC)
    ctx = browser.new_context()
    page = ctx.new_page()
    console_errors = []
    page.on('console', lambda m: console_errors.append(m.text) if m.type == 'error' else None)
    page.on('pageerror', lambda e: console_errors.append(str(e)))

    # --- 1. Login via API (cookie set for this context) ---
    page.goto(BASE + '/login')
    page.evaluate("""async () => {
        const r = await fetch('/api/auth/login', {method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify({username:'admin', password:'GameRoom#Sandbox2026'})});
        return r.status;
    }""")
    page.wait_for_timeout(500)

    # --- 2. First app load: SW must register under versioned URL and activate ---
    page.goto(BASE + '/')
    page.wait_for_function("document.querySelector('#app-container') !== null", timeout=15000)
    reg = page.evaluate("""async () => {
        const r = await navigator.serviceWorker.getRegistration();
        return r ? {active: !!r.active, waiting: !!r.waiting,
                    scriptURL: r.active && r.active.scriptURL} : null;
    }""")
    print('registration:', reg)
    check('SW registered & active with versioned URL (?v=9)',
          bool(reg and reg['scriptURL'] and 'sw.js?v=9' in reg['scriptURL']))

    keys = page.evaluate("() => caches.keys()")
    print('cache keys after first load:', keys)
    check('new cache gameroom-pwa-v9-auth exists', 'gameroom-pwa-v9-auth' in keys)

    page.wait_for_timeout(1500)
    cached = page.evaluate("""async () => {
        const c = await caches.open('gameroom-pwa-v9-auth');
        const ks = await c.keys();
        return ks.map(k => { const u = new URL(k.url); return u.pathname + u.search; });
    }""")
    print('cached entries:', cached)
    check('versioned css/js cached under ?v=9 keys',
          '/css/spider_verse.css?v=9' in cached and '/js/app.js?v=9' in cached)

    # --- 3. Seed a legacy v8 cache with STALE unversioned assets (PR#6 residue) ---
    page.evaluate("""async () => {
        const legacy = await caches.open('gameroom-pwa-v8-auth');
        await legacy.put('/js/app.js', new Response('STALE_OLD_APP_JS', {headers:{'Content-Type':'application/javascript'}}));
        await legacy.put('/css/spider_verse.css', new Response('.stale{color:red}', {headers:{'Content-Type':'text/css'}}));
    }""")

    # --- 4. Normal reload (no Ctrl+F5): styles applied, app booted, old cache purged ---
    page.reload(wait_until='load')
    page.wait_for_timeout(2000)
    styled = page.evaluate("""() => {
        const btn = document.querySelector('.nav-item');
        const cs = btn ? getComputedStyle(btn) : null;
        return {
            cssLoaded: [...document.styleSheets].some(s => s.href && s.href.includes('spider_verse')),
            btnBorder: cs ? cs.border : null,
            btnRadius: cs ? cs.borderRadius : null,
            appBooted: typeof app !== 'undefined' && app.games !== undefined && app.currentTab !== undefined,
            tabVisible: !!document.querySelector('#tab-playing'),
        };
    }""")
    print('styled:', styled)
    check('CSS actually applied to .nav-item (not default HTML look)',
          styled['cssLoaded'] and styled['btnRadius'] not in (None, '0px'))
    check('app.js booted (app object initialised)', styled['appBooted'])

    keys = page.evaluate("() => caches.keys()")
    print('cache keys after reload/activate:', keys)
    check('legacy v8 cache purged on activate', 'gameroom-pwa-v8-auth' not in keys)

    stale_served = page.evaluate("""async () => {
        // Even if somehow matched, ensure current page did NOT run STALE_OLD_APP_JS
        return typeof app === 'undefined';
    }""")
    check('stale unversioned app.js not executing', not stale_served)

    # --- 5. API never served from poisoned cache ---
    res = page.evaluate("""async () => {
        const c = await caches.open('gameroom-pwa-v9-auth');
        await c.put('/api/games', new Response('{"CORRUPTED":true}', {status:200}));
        const r = await fetch('/api/games');
        const j = await r.json();
        return {corrupted: j.CORRUPTED === true, sample: Object.keys(j).slice(0,5)};
    }""")
    print('api-from-cache probe:', res)
    check('API response comes from network, not poisoned cache', not res['corrupted'])

    # --- 6. HTML not stored in SW cache ---
    html_cached = page.evaluate("""async () => {
        const c = await caches.open('gameroom-pwa-v9-auth');
        return !!(await c.match('/')) || !!(await c.match('/index.html'));
    }""")
    check('index.html NOT present in SW cache', not html_cached)

    # --- 7. Release calendar tab renders without infinite spinner ---
    page.click('[data-tab="release-calendar"]')
    page.wait_for_timeout(3000)
    cal = page.evaluate("""() => {
        const el = document.getElementById('calendar-weeks-container');
        return el ? el.innerText.slice(0,150) : null;
    }""")
    print('calendar container text:', repr(cal))
    check('calendar pane shows content or explicit error (no RAWG key -> graceful message)',
          cal is not None and 'Загружаем релизы' not in cal)

    fatal = [e for e in console_errors if 'STALE' in e or 'ReferenceError' in e or 'SyntaxError' in e]
    check('no fatal page JS errors', not fatal)
    if console_errors: print('console errors sample:', console_errors[:5])

    browser.close()

print('\nSUMMARY:', sum(1 for _, v in ok if v), '/', len(ok), 'checks passed')
