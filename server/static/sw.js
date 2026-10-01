const CACHE_NAME = 'gameroom-pwa-v8-auth';

// Only cache immutable static assets; NEVER cache HTML shell or API responses
const STATIC_ASSETS = [
  '/css/spider_verse.css',
  '/js/app.js',
  '/manifest.json?v=8',
  '/favicon.ico?v=8',
  '/favicon.png?v=8',
  '/assets/icon-192.png?v=8',
  '/assets/icon-512.png?v=8',
  '/assets/apple-touch-icon.png?v=8',
  '/assets/ratings/izumitelno.svg',
  '/assets/ratings/pohvalno.svg',
  '/assets/ratings/prohodnyak.svg',
  '/assets/ratings/musor.svg'
];

self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(STATIC_ASSETS).catch(() => {});
    })
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys.map(key => {
          // Immediately purge old caches (including v6 with cached index.html)
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;

  // 1. API calls are strictly NETWORK ONLY - never cached or served from cache
  if (event.request.url.includes('/api/')) {
    event.respondWith(fetch(event.request));
    return;
  }

  // 2. Navigation / HTML requests are strictly NETWORK FIRST
  // This guarantees unauthenticated users receive the server login page
  const isHtml = event.request.mode === 'navigate' ||
    event.request.destination === 'document' ||
    (event.request.headers.get('accept') && event.request.headers.get('accept').includes('text/html'));

  if (isHtml) {
    event.respondWith(
      fetch(event.request).catch(() => caches.match(event.request))
    );
    return;
  }

  // 3. Static assets (CSS/JS/images) use Cache First with network fallback
  event.respondWith(
    caches.match(event.request).then(cached => {
      if (cached) return cached;
      return fetch(event.request).then(response => {
        if (response && response.status === 200) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      });
    })
  );
});
