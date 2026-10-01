const CACHE_NAME = 'game-room-v1';
const ASSETS_TO_CACHE = [
  'lib/react.production.min.js',
  'lib/react-dom.production.min.js',
  'lib/babel.min.js',
  'lib/tailwindcss.js',
  'lib/lucide.js',
  'lib/confetti.browser.min.js',
  'lib/chart.umd.min.js',
  'css/styles.css',
  'css/tailwind.css',
  'css/fonts.css'
];

// Установка Service Worker
self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS_TO_CACHE);
    })
  );
});

// Активация - очистка старых кэшей
self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keyList) => {
      return Promise.all(
        keyList.map((key) => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    })
  );
});

// Обработка запросов
self.addEventListener('fetch', (e) => {
  e.respondWith(
    caches.match(e.request).then((response) => {
      return response || fetch(e.request);
    })
  );
});
