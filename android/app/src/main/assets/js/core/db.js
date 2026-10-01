// db.js - Работа с IndexedDB для кэширования данных

const DB_NAME = 'GameRoomDB';
const DB_VERSION = 1;

const STORES = {
  GAMES: 'games',
  CARS: 'game_covers',
  CACHE: 'api_cache',
  SYNC_QUEUE: 'sync_queue'
};

function openDB() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    
    request.onupgradeneeded = (event) => {
      const db = event.target.result;
      
      // Store for games
      if (!db.objectStoreNames.contains(STORES.GAMES)) {
        db.createObjectStore(STORES.GAMES, { keyPath: 'id' });
      }
      
      // Store for game covers (as blobs)
      if (!db.objectStoreNames.contains(STORES.CARS)) {
        const coverStore = db.createObjectStore(STORES.CARS, { keyPath: 'url' });
        coverStore.createIndex('timestamp', 'timestamp');
      }
      
      // Store for API cache
      if (!db.objectStoreNames.contains(STORES.CACHE)) {
        const cacheStore = db.createObjectStore(STORES.CACHE, { keyPath: 'key' });
        cacheStore.createIndex('timestamp', 'timestamp');
      }
      
      // Store for sync queue
      if (!db.objectStoreNames.contains(STORES.SYNC_QUEUE)) {
        const queueStore = db.createObjectStore(STORES.SYNC_QUEUE, { keyPath: 'id', autoIncrement: true });
        queueStore.createIndex('timestamp', 'timestamp');
      }
    };
    
    request.onsuccess = (event) => resolve(event.target.result);
    request.onerror = (event) => reject(event.target.error);
  });
}

async function saveGameCover(url, blob) {
  const db = await openDB();
  const tx = db.transaction(STORES.CARS, 'readwrite');
  const store = tx.objectStore(STORES.CARS);
  store.put({ url, blob, timestamp: Date.now() });
  return tx.complete;
}

async function getGameCover(url) {
  const db = await openDB();
  const tx = db.transaction(STORES.CARS, 'readonly');
  const store = tx.objectStore(STORES.CARS);
  const request = store.get(url);
  
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result?.blob || null);
    request.onerror = () => reject(request.error);
  });
}

// Сохранение API ответа в IndexedDB
async function saveAPICache(key, data) {
  const db = await openDB();
  const tx = db.transaction(STORES.CACHE, 'readwrite');
  const store = tx.objectStore(STORES.CACHE);
  store.put({ key, data, timestamp: Date.now() });
  return tx.complete;
}

// Получение API ответа из IndexedDB
async function getAPICache(key) {
  const db = await openDB();
  const tx = db.transaction(STORES.CACHE, 'readonly');
  const store = tx.objectStore(STORES.CACHE);
  const request = store.get(key);
  
  return new Promise((resolve) => {
    request.onsuccess = () => {
      const result = request.result;
      if (result && Date.now() - result.timestamp < 3600000) { // 1 час
        resolve(result.data);
      } else {
        resolve(null);
      }
    };
    request.onerror = () => resolve(null);
  });
}

// Синхронизация очереди
async function processSyncQueue() {
  const db = await openDB();
  const tx = db.transaction(STORES.SYNC_QUEUE, 'readonly');
  const store = tx.objectStore(STORES.SYNC_QUEUE);
  const request = store.getAll();
  
  return new Promise((resolve) => {
    request.onsuccess = () => {
      const queue = request.result;
      resolve(queue);
    };
  });
}

async function addSyncQueueItem(action, data) {
  const db = await openDB();
  const tx = db.transaction(STORES.SYNC_QUEUE, 'readwrite');
  const store = tx.objectStore(STORES.SYNC_QUEUE);
  store.add({ action, data, timestamp: Date.now() });
  return tx.complete;
}

async function clearSyncQueue() {
  const db = await openDB();
  const tx = db.transaction(STORES.SYNC_QUEUE, 'readwrite');
  const store = tx.objectStore(STORES.SYNC_QUEUE);
  store.clear();
  return tx.complete;
}

// Экспортируем функции в глобальную область видимости для использования в GameRoom.html
window.openDB = openDB;
window.saveGameCover = saveGameCover;
window.getGameCover = getGameCover;
window.saveAPICache = saveAPICache;
window.getAPICache = getAPICache;
window.processSyncQueue = processSyncQueue;
window.addSyncQueueItem = addSyncQueueItem;
window.clearSyncQueue = clearSyncQueue;
window.STORES = STORES;
