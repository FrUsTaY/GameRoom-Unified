const CACHE_NAME = 'gameroom-pwa-v6-room-icon';
const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/css/spider_verse.css',
  '/js/app.js',
  '/manifest.json?v=6',
  '/favicon.ico?v=6',
  '/assets/icon-192.png?v=6',
  '/assets/icon-512.png?v=6',
  '/assets/apple-touch-icon.png?v=6',
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
  if (event.request.url.includes('/api/')) {
    event.respondWith(
      fetch(event.request).catch(() => caches.match(event.request))
    );
    return;
  }
  event.respondWith(
    caches.match(event.request).then(cached => {
      const networked = fetch(event.request).then(response => {
        if (response && response.status === 200) {
          const cacheCopy = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, cacheCopy));
        }
        return response;
      }).catch(() => cached);
      return cached || networked;
    })
  );
});
