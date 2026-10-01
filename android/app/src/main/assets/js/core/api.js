// api.js - Умная система API с поддержкой кэширования и офлайн-режимов

// Подключение db.js функций через глобальные переменные (так как это не ES modules в browser)
// db.js будет добавлен через script tag в GameRoom.html до api.js

const API_MODES = {
  ONLINE: 'online',
  OFFLINE: 'offline',
  PARTIAL: 'partial'
};

const API_CONFIG = {
  mandatory: ['localStorage', 'cache', 'rawgCovers'],
  optional: ['RAWG', 'GIGACHAT', 'YOUTUBE', 'YANDEX_DISK']
};

let currentMode = API_MODES.ONLINE;
let apiCache = new Map();

// Проверка интернета
function checkOnline() {
  return navigator.onLine;
}

// Детекция режима
function detectMode() {
  if (!checkOnline()) return API_MODES.OFFLINE;
  
  // Проверка API ключей и доступности сервисов
  const hasRawgKey = !!localStorage.getItem('rawg_api_key');
  const hasGigaKey = !!localStorage.getItem('gigachat_auth_key');
  const hasYtKey = !!localStorage.getItem('youtube_api_key');
  const hasYandexKey = !!localStorage.getItem('yandex_oauth_token');
  
  if (hasRawgKey && hasGigaKey && hasYtKey && hasYandexKey) {
    return API_MODES.ONLINE;
  }
  return API_MODES.PARTIAL;
}

// Кэширование данных (localStorage для простых данных)
function cacheData(key, data) {
  apiCache.set(key, { data, timestamp: Date.now() });
  localStorage.setItem(`api_cache_${key}`, JSON.stringify({ data, timestamp: Date.now() }));
}

// Получение из кэша (localStorage)
function getCachedData(key) {
  const cached = apiCache.get(key);
  if (cached && Date.now() - cached.timestamp < 3600000) { // 1 час
    return cached.data;
  }
  
  const localStorageCached = localStorage.getItem(`api_cache_${key}`);
  if (localStorageCached) {
    const parsed = JSON.parse(localStorageCached);
    if (Date.now() - parsed.timestamp < 3600000) {
      return parsed.data;
    }
  }
  return null;
}

// RAWG API wrapper с кэшированием обложек
async function fetchRAWG(search, apiKey) {
  const cacheKey = `rawg_search_${search}`;
  
  // Проверяем кэш в IndexedDB (если db.js загружен)
  if (typeof getAPICache === 'function') {
    const dbCached = await getAPICache(cacheKey);
    if (dbCached) return dbCached;
  }
  
  // Проверяем кэш в localStorage
  const localStorageCached = getCachedData(cacheKey);
  if (localStorageCached) return localStorageCached;
  
  if (currentMode === API_MODES.OFFLINE) {
    return { results: [], error: 'OFFLINE' };
  }
  
  try {
    const response = await fetch(`https://api.rawg.io/api/games?key=${apiKey}&search=${encodeURIComponent(search)}&page_size=5`);
    const data = await response.json();
    
    // Сохраняем в оба кэша
    cacheData(cacheKey, data);
    if (typeof saveAPICache === 'function') {
      await saveAPICache(cacheKey, data);
    }
    
    // Кэшируем обложки игр
    if (data.results) {
      for (const game of data.results) {
        if (game.background_image) {
          try {
            const imageResponse = await fetch(game.background_image);
            if (imageResponse.ok) {
              const blob = await imageResponse.blob();
              if (typeof saveGameCover === 'function') {
                await saveGameCover(game.background_image, blob);
              }
            }
          } catch (e) {
            console.error('Ошибка кэширования обложки:', e);
          }
        }
      }
    }
    
    return data;
  } catch (error) {
    console.error('RAWG API error:', error);
    return { results: [], error: error.message };
  }
}

// GigaChat API wrapper
async function fetchGigaChat(messages, apiKey, token, expiry) {
  const cacheKey = `gigachat_${JSON.stringify(messages)}`;
  
  // Проверяем кэш в IndexedDB (если db.js загружен)
  if (typeof getAPICache === 'function') {
    const dbCached = await getAPICache(cacheKey);
    if (dbCached) return dbCached;
  }
  
  // Проверяем кэш в localStorage
  const localStorageCached = getCachedData(cacheKey);
  if (localStorageCached) return localStorageCached;
  
  if (currentMode === API_MODES.OFFLINE) {
    return { error: 'OFFLINE' };
  }
  
  try {
    // Проверка токена
    if (!token || !expiry || Date.now() >= expiry - 60000) {
      if (!apiKey) {
        throw new Error('Не указан ключ авторизации GigaChat');
      }
      
      let finalAuthKey = apiKey;
      const isUUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(apiKey);
      if (isUUID) {
          const clientId = '019d9b23-6f39-7aa5-aedd-7f181974f3f9';
          finalAuthKey = btoa(`${clientId}:${apiKey}`);
      }

      const url = 'https://ngw.devices.sberbank.ru:9443/api/v2/oauth';
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          'Accept': 'application/json',
          'RqUID': crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(),
          'Authorization': `Basic ${finalAuthKey}`
        },
        body: 'scope=GIGACHAT_API_PERS'
      });
      
      if (!response.ok) {
        throw new Error(`Ошибка получения токена: ${response.status}`);
      }
      
      const data = await response.json();
      token = data.access_token;
      expiry = Date.now() + (data.expires_in * 1000);
    }
    
    const requestBody = {
      model: 'GigaChat',
      messages: messages,
      temperature: 0.7,
      max_tokens: 2048
    };
    
    const response = await fetch('https://gigachat.devices.sberbank.ru/api/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify(requestBody)
    });
    
    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(`Ошибка GigaChat: ${errorData.message || response.statusText}`);
    }
    
    const data = await response.json();
    cacheData(cacheKey, data);
    if (typeof saveAPICache === 'function') {
      await saveAPICache(cacheKey, data);
    }
    return data;
  } catch (error) {
    console.error('GigaChat API error:', error);
    return { error: error.message };
  }
}

// YouTube API wrapper
async function fetchYouTube(videoQuery, apiKey) {
  const cacheKey = `youtube_${videoQuery}`;
  
  // Проверяем кэш в IndexedDB (если db.js загружен)
  if (typeof getAPICache === 'function') {
    const dbCached = await getAPICache(cacheKey);
    if (dbCached) return dbCached;
  }
  
  // Проверяем кэш в localStorage
  const localStorageCached = getCachedData(cacheKey);
  if (localStorageCached) return localStorageCached;
  
  if (currentMode === API_MODES.OFFLINE) {
    return { error: 'OFFLINE' };
  }
  
  try {
    const url = new URL('https://www.googleapis.com/youtube/v3/search');
    url.searchParams.set('part', 'snippet');
    url.searchParams.set('type', 'video');
    url.searchParams.set('maxResults', '1');
    url.searchParams.set('q', `${videoQuery} трейлер игра`);
    url.searchParams.set('key', apiKey);
    
    const response = await fetch(url.toString());
    const data = await response.json();
    cacheData(cacheKey, data);
    if (typeof saveAPICache === 'function') {
      await saveAPICache(cacheKey, data);
    }
    return data;
  } catch (error) {
    console.error('YouTube API error:', error);
    return { error: error.message };
  }
}

// Яндекс.Диск API wrapper
async function fetchYandexDisk(path, yandexToken, method = 'GET', body = null) {
  if (currentMode === API_MODES.OFFLINE) {
    return { error: 'OFFLINE' };
  }
  
  try {
    const url = new URL(`https://cloud-api.yandex.net/v1/disk/resources${path}`);
    
    const response = await fetch(url.toString(), {
      method: method,
      headers: {
        'Authorization': `OAuth ${yandexToken}`,
        'Content-Type': 'application/json'
      },
      body: body ? JSON.stringify(body) : null
    });
    
    const data = await response.json();
    return data;
  } catch (error) {
    console.error('Yandex Disk API error:', error);
    return { error: error.message };
  }
}

// Делаем функции глобально доступными для использования в HTML
window.detectMode = detectMode;
window.API_MODES = API_MODES;
window.checkOnline = checkOnline;
window.cacheData = cacheData;
window.getCachedData = getCachedData;
window.fetchRAWG = fetchRAWG;

// Gemini API wrapper
async function fetchGemini(messages, apiKey) {
  const cacheKey = `gemini_${JSON.stringify(messages)}`;

  // Проверяем кэш в IndexedDB (если db.js загружен)
  if (typeof getAPICache === 'function') {
    const dbCached = await getAPICache(cacheKey);
    if (dbCached) return dbCached;
  }

  // Проверяем кэш в localStorage
  const localStorageCached = getCachedData(cacheKey);
  if (localStorageCached) return localStorageCached;

  if (currentMode === API_MODES.OFFLINE) {
    return { error: 'OFFLINE' };
  }

  try {
    if (!apiKey) {
      throw new Error('Не указан ключ авторизации Gemini');
    }

    const response = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${apiKey}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(messages)
    });

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(`Ошибка Gemini: ${errorData.error?.message || response.statusText}`);
    }

    const data = await response.json();
    cacheData(cacheKey, data);
    if (typeof saveAPICache === 'function') {
      await saveAPICache(cacheKey, data);
    }
    return data;
  } catch (error) {
    console.error('Gemini API error:', error);
    return { error: error.message };
  }
}

window.fetchGigaChat = fetchGigaChat;
window.fetchGemini = fetchGemini;
window.fetchYouTube = fetchYouTube;
window.fetchYandexDisk = fetchYandexDisk;
window.currentMode = currentMode;
window.API_CONFIG = API_CONFIG;
