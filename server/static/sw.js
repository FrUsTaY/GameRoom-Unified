/**
 * GAME-ROOM Service Worker (PWA) — v9
 *
 * Cache-invalidation strategy (single source of truth):
 *   Every deploy must bump ASSET_VERSION below AND the ?v= query in
 *   index.html / login.html for /css/spider_verse.css and /js/app.js.
 *   Versioned URLs are unique cache keys, so a bumped version makes any
 *   stale CSS/JS entry unreachable by design — old entries are purged on
 *   activate. No manual CACHE_NAME renaming is required to invalidate
 *   static assets (CACHE_NAME is still available as an emergency full-purge
 *   lever: bump it if you ever need to drop ALL runtime-cached entries).
 *
 * Policies:
 *   - HTML (navigations) : NETWORK ONLY (auth-sensitive; server sends no-store)
 *   - /api/*             : NETWORK ONLY (never cached — protects sessions)
 *   - Same-origin static : revalidated cache (serve cached copy instantly,
 *                          refresh network in background; non-200 or changed
 *                          ETag purges the entry so next load gets fresh file)
 *   - Cross-origin GET   : pass-through
 */

const ASSET_VERSION = '9';
const CACHE_NAME = 'gameroom-pwa-v' + ASSET_VERSION + '-auth';

// Precached shell assets. CSS/JS are intentionally NOT precached here:
// they are picked up by the revalidate path under the exact versioned URL
// the page requests, which keeps cache keys aligned with index.html links.
const STATIC_ASSETS = [
  '/manifest.json?v=' + ASSET_VERSION,
  '/favicon.ico?v=' + ASSET_VERSION,
  '/favicon.png?v=' + ASSET_VERSION,
  '/assets/icon-192.png?v=' + ASSET_VERSION,
  '/assets/icon-512.png?v=' + ASSET_VERSION,
  '/assets/apple-touch-icon.png?v=' + ASSET_VERSION,
  '/assets/ratings/izumitelno.svg',
  '/assets/ratings/pohvalno.svg',
  '/assets/ratings/prohodnyak.svg',
  '/assets/ratings/musor.svg'
];

self.addEventListener('install', event => {
  // Do NOT call skipWaiting() here: let the browser swap SW versions at the
  // next normal navigation (the standard 24h update check already fetches
  // the new sw.js byte-by-byte against index.html's versioned links).
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(STATIC_ASSETS))
      .catch(() => {})
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => Promise.all(
      keys.map(key => {
        // Purge every older cache, including legacy v8-auth whose
        // unversioned /js/app.js & /css/spider_verse.css entries caused
        // the stale-shell bug after deploys.
        if (key !== CACHE_NAME) return caches.delete(key);
      })
    )).then(() => self.clients.claim())
  );
});

function isApiUrl(url) {
  return url.pathname === '/api' || url.pathname.startsWith('/api/');
}

function isHtmlRequest(request) {
  if (request.mode === 'navigate') return true;
  if (request.destination === 'document') return true;
  const accept = request.headers.get('accept');
  return !!(accept && accept.includes('text/html'));
}

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  // Never intercept cross-origin requests (RAWG images, YouTube, etc.)
  if (url.origin !== self.location.origin) return;

  // 1. API calls are strictly NETWORK ONLY — never cached or served from cache.
  if (isApiUrl(url)) {
    event.respondWith(fetch(request));
    return;
  }

  // 2. Navigations / HTML are NETWORK ONLY (with an offline fallback taken
  //    from the HTTP cache only, never from our own caches). This guarantees
  //    unauthenticated users always receive the real server login page and
  //    HTML is never served stale.
  if (isHtmlRequest(request)) {
    event.respondWith(
      fetch(request, { cache: 'no-store' }).catch(() =>
        fetch(request, { cache: 'default' })
      )
    );
    return;
  }

  // 3. Same-origin static assets: revalidated cache.
  event.respondWith(revalidateStatic(request));
});

async function revalidateStatic(request) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);

  try {
    const network = await fetch(request, { cache: 'no-store' });
    if (network && network.status === 200) {
      // If both copies carry validators and the ETag changed, a new file
      // version was deployed — replace the entry atomically.
      const cachedEtag = cached ? cached.headers.get('etag') : null;
      const netEtag = network.headers.get('etag');
      if (!cached || !cachedEtag || !netEtag || cachedEtag !== netEtag) {
        const clone = network.clone();
        await cache.put(request, clone);
      }
      return network;
    }
    // Non-200 (e.g. 401/404/5xx): never store it; drop any stale entry.
    if (cached) await cache.delete(request);
    if (cached && network && network.type === 'opaque') return cached;
    return cached || network;
  } catch (err) {
    // Offline: serve last known-good copy if we have one.
    if (cached) return cached;
    throw err;
  }
}
