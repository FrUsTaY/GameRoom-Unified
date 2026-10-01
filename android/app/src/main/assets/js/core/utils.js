// utils.js - Утилиты для приложения (без ES modules для browser)

// Форматирование времени
function pluralHours(h) {
  if (h % 10 === 1 && h % 100 !== 11) return 'час';
  if (h % 10 >= 2 && h % 10 <= 4 && (h % 100 < 10 || h % 100 >= 20)) return 'часа';
  return 'часов';
}

function pluralMinutes(m) {
  if (m % 10 === 1 && m % 100 !== 11) return 'минута';
  if (m % 10 >= 2 && m % 10 <= 4 && (m % 100 < 10 || m % 100 >= 20)) return 'минуты';
  return 'минут';
}

// Извлечение названия игры из текста
function extractGameName(text) {
  if (!text) return null;
  
  const cleanName = (name) => {
    return name
      .replace(/^[*"'\\-—\\s]+|[*"'\\-—\\s]+$/g, '')
      .replace(/\*/g, '')
      .replace(/\s*\(?от\s+.*$/i, '')
      .replace(/\s*\(?студия\s+.*$/i, '')
      .replace(/[()]/g, '')
      .trim();
  };
  
  const советуетMatch = text.match(/(?:Советую|Рекомендую|Посоветую)[:\s]+([^.!?\\n]+?)(?:[.!?\\n]|$)/i);
  if (советуетMatch) return cleanName(советуетMatch[1]);
  
  const quoteMatch = text.match(/[\""]([^\""]+)[\""]/);
  if (quoteMatch) return cleanName(quoteMatch[1]);
  
  const sentenceMatch = text.match(/^[^.!?\\n]+/);
  if (sentenceMatch) return cleanName(sentenceMatch[0]);
  
  return null;
}

// Сравнение версий
function compareVersion(v1, v2) {
  const parts1 = v1.split('.').map(Number);
  const parts2 = v2.split('.').map(Number);
  
  for (let i = 0; i < Math.max(parts1.length, parts2.length); i++) {
    const p1 = parts1[i] || 0;
    const p2 = parts2[i] || 0;
    
    if (p1 > p2) return 1;
    if (p1 < p2) return -1;
  }
  return 0;
}

// Умная сортировка массива
function smartSort(arr, key, descending = false) {
  return arr.sort((a, b) => {
    let valA = a[key];
    let valB = b[key];
    
    // Если значения числовые
    if (!isNaN(parseFloat(valA)) && !isNaN(parseFloat(valB))) {
      valA = parseFloat(valA) || 0;
      valB = parseFloat(valB) || 0;
      return descending ? valB - valA : valA - valB;
    }
    
    // Строковая сортировка
    valA = String(valA).toLowerCase();
    valB = String(valB).toLowerCase();
    
    if (valA < valB) return descending ? 1 : -1;
    if (valA > valB) return descending ? -1 : 1;
    return 0;
  });
}

// Генерация случайного ID
function generateId() {
  return Date.now().toString(36) + Math.random().toString(36).substr(2);
}

// Проверка, является ли строка числом
function isNumber(value) {
  return !isNaN(parseFloat(value)) && isFinite(value);
}

// Ограничение длины строки
function truncate(str, maxLength, suffix = '...') {
  if (str.length <= maxLength) return str;
  return str.slice(0, maxLength - suffix.length) + suffix;
}

// Преобразование Blob в Data URL
function blobToDataURL(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

// Кэширование изображения через IndexedDB
async function cacheImage(url, blob) {
  try {
    await saveGameCover(url, blob);
    return true;
  } catch (error) {
    console.error('Ошибка кэширования изображения:', error);
    return false;
  }
}

// Получение закэшированного изображения
async function getCachedImage(url) {
  try {
    return await getGameCover(url);
  } catch (error) {
    console.error('Ошибка получения закэшированного изображения:', error);
    return null;
  }
}

// Создание превью для изображения
function createImagePreview(blob) {
  return URL.createObjectURL(blob);
}

// Экспортируем функции в глобальную область видимости
window.pluralHours = pluralHours;
window.pluralMinutes = pluralMinutes;
window.extractGameName = extractGameName;
window.compareVersion = compareVersion;
window.smartSort = smartSort;
window.generateId = generateId;
window.isNumber = isNumber;
window.truncate = truncate;
window.blobToDataURL = blobToDataURL;
window.cacheImage = cacheImage;
window.getCachedImage = getCachedImage;
window.createImagePreview = createImagePreview;
