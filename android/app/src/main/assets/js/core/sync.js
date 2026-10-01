// sync.js - Клиентский движок двусторонней распределенной синхронизации GameRoom (Android ↔ Server)

(function(window) {
  'use strict';

  const SYNC_STORAGE_KEYS = {
    SERVER_URL: 'game_room_sync_server_url',
    SYNC_TOKEN: 'game_room_sync_token',
    LAST_SYNC: 'game_room_last_sync',
    CLIENT_ID: 'game_room_client_id',
    SYNC_QUEUE: 'game_room_sync_queue',
    AUTO_SYNC: 'game_room_auto_sync_enabled',
    SEQ_COUNTER: 'game_room_sync_seq'
  };

  // --- UUID Generator (RFC4122 v4) ---
  function generateUuid() {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID();
    }
    // Fallback using crypto.getRandomValues
    if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
      return ([1e7]+-1e3+-4e3+-8e3+-1e11).replace(/[018]/g, c =>
        (c ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> c / 4).toString(16)
      );
    }
    // Simple timestamp fallback
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
      const r = Math.random() * 16 | 0, v = c === 'x' ? r : (r & 0x3 | 0x8);
      return v.toString(16);
    });
  }

  function getClientId() {
    let cid = localStorage.getItem(SYNC_STORAGE_KEYS.CLIENT_ID);
    if (!cid) {
      cid = 'android-' + generateUuid().substring(0, 8);
      localStorage.setItem(SYNC_STORAGE_KEYS.CLIENT_ID, cid);
    }
    return cid;
  }

  function getNextSeq() {
    let seq = parseInt(localStorage.getItem(SYNC_STORAGE_KEYS.SEQ_COUNTER) || '0', 10);
    seq += 1;
    localStorage.setItem(SYNC_STORAGE_KEYS.SEQ_COUNTER, seq.toString());
    return seq;
  }

  // --- Sync Queue Management (localStorage based for synchronous UI safety) ---

  function getSyncQueue() {
    try {
      const raw = localStorage.getItem(SYNC_STORAGE_KEYS.SYNC_QUEUE);
      return raw ? JSON.parse(raw) : [];
    } catch (e) {
      console.error('Error reading sync queue:', e);
      return [];
    }
  }

  function saveSyncQueue(queue) {
    try {
      localStorage.setItem(SYNC_STORAGE_KEYS.SYNC_QUEUE, JSON.stringify(queue));
    } catch (e) {
      console.error('Error saving sync queue:', e);
    }
  }

  function enqueueAction(action, uuid, payload) {
    if (!uuid) return;
    const queue = getSyncQueue();
    const nowIso = new Date().toISOString();
    const seq = getNextSeq();

    // Compact queue for same UUID
    const existingIndex = queue.findIndex(item => item.uuid === uuid);

    if (existingIndex >= 0) {
      const existing = queue[existingIndex];
      if (existing.action === 'create' && action === 'delete') {
        // Created and deleted offline -> completely cancel out
        queue.splice(existingIndex, 1);
        saveSyncQueue(queue);
        return;
      }
      if (existing.action === 'create' && action === 'update') {
        // Merge updates into create payload
        existing.payload = Object.assign({}, existing.payload, payload);
        existing.timestamp = nowIso;
        existing.client_seq = seq;
        saveSyncQueue(queue);
        return;
      }
      if (existing.action === 'update' && action === 'update') {
        existing.payload = Object.assign({}, existing.payload, payload);
        existing.timestamp = nowIso;
        existing.client_seq = seq;
        saveSyncQueue(queue);
        return;
      }
      if (existing.action === 'update' && action === 'delete') {
        existing.action = 'delete';
        existing.payload = null;
        existing.timestamp = nowIso;
        existing.client_seq = seq;
        saveSyncQueue(queue);
        return;
      }
    }

    queue.push({
      action: action, // 'create' | 'update' | 'delete'
      uuid: uuid,
      client_seq: seq,
      timestamp: nowIso,
      payload: payload || null
    });

    saveSyncQueue(queue);
  }

  function removeAppliedFromQueue(appliedUuids) {
    if (!appliedUuids || !appliedUuids.length) return;
    const set = new Set(appliedUuids);
    const queue = getSyncQueue().filter(item => !set.has(item.uuid));
    saveSyncQueue(queue);
  }

  function clearSyncQueue() {
    localStorage.removeItem(SYNC_STORAGE_KEYS.SYNC_QUEUE);
  }

  // --- Entity Mapping Helpers ---

  const STATUS_ANDROID_TO_SERVER = {
    'Пройдено': 'completed',
    'В процессе': 'playing',
    'Брошено': 'dropped',
    'В бэклоге': 'backlog',
    'wishlist': 'wishlist',
    'completed': 'completed',
    'playing': 'playing',
    'dropped': 'dropped',
    'backlog': 'backlog'
  };

  const STATUS_SERVER_TO_ANDROID = {
    'completed': 'Пройдено',
    'playing': 'В процессе',
    'dropped': 'Брошено',
    'paused': 'В процессе',
    'backlog': 'В процессе',
    'wishlist': 'wishlist'
  };

  function parseUserScore(ratingStr) {
    if (!ratingStr || ratingStr === '-') return 0;
    const match = String(ratingStr).match(/^(\d+)/);
    return match ? parseInt(match[1], 10) : 0;
  }

  function gradeToRatingStr(grade, userScore) {
    if (userScore && userScore > 0) return `${userScore}/10`;
    switch (grade) {
      case 'izumitelno': return '10/10';
      case 'pohvalno': return '8/10';
      case 'prohodnyak': return '6/10';
      case 'musor': return '3/10';
      default: return '-';
    }
  }

  function androidGameToSyncItem(game, clientSeq) {
    const itemUuid = game.uuid || game.id || generateUuid();
    const playtimeMinutes = Math.round(parseFloat(game.time || 0) * 60);
    const userScore = parseUserScore(game.rating);

    return {
      uuid: itemUuid,
      client_seq: clientSeq || getNextSeq(),
      title: game.title || 'Untitled Game',
      status: STATUS_ANDROID_TO_SERVER[game.status] || 'completed',
      platform: game.platform || 'Домашний ПК',
      platforms_list: [game.platform || 'Домашний ПК'],
      user_playtime_minutes: playtimeMinutes,
      playtime_main: parseFloat(game.avgPlaytime || 0),
      rating_grade: game.rating_grade || '',
      user_score: userScore,
      cover_url: game.coverUrl || '',
      background_url: game.coverUrl || '',
      notes: game.note || '',
      user_review: game.status === 'Пройдено' ? (game.note || '') : '',
      completed_at: game.status === 'Пройдено' ? (game.completed_at || game.updated_at || new Date().toISOString()) : '',
      created_at: game.created_at || game.updated_at || new Date().toISOString(),
      updated_at: game.updated_at || new Date().toISOString(),
      rawg_id: game.rawg_id || null,
      genres: game.genres || '',
      developer: game.developer || '',
      publisher: game.publisher || '',
      priority: game.priority || 'medium',
      is_favorite: game.is_favorite || 0
    };
  }

  function androidWishlistToSyncItem(wItem, clientSeq) {
    const itemUuid = wItem.uuid || wItem.id || generateUuid();
    return {
      uuid: itemUuid,
      client_seq: clientSeq || getNextSeq(),
      title: wItem.title || 'Untitled Game',
      status: 'wishlist',
      platform: wItem.platform || 'Домашний ПК',
      platforms_list: [wItem.platform || 'Домашний ПК'],
      user_playtime_minutes: 0,
      playtime_main: parseFloat(wItem.avgPlaytime || 0),
      rating_grade: '',
      user_score: 0,
      cover_url: wItem.coverUrl || '',
      background_url: wItem.coverUrl || '',
      notes: wItem.note || '',
      release_date: wItem.expectedYear ? `${wItem.expectedYear}-01-01` : '',
      created_at: wItem.created_at || wItem.updated_at || new Date().toISOString(),
      updated_at: wItem.updated_at || new Date().toISOString()
    };
  }

  function serverGameToAndroidGame(sGame) {
    const hours = (Math.max(0, sGame.user_playtime_minutes || 0) / 60.0).toFixed(1);
    const ratingStr = gradeToRatingStr(sGame.rating_grade, sGame.user_score);
    const androidStatus = STATUS_SERVER_TO_ANDROID[sGame.status] || 'В процессе';

    let yearStr = '2026';
    let monthStr = 'Апрель';
    const dateSrc = sGame.completed_at || sGame.release_date || sGame.created_at;
    if (dateSrc) {
      try {
        const d = new Date(dateSrc);
        if (!isNaN(d.getTime())) {
          yearStr = d.getFullYear().toString();
          const months = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'];
          monthStr = months[d.getMonth()];
        }
      } catch (e) {}
    }

    return {
      id: sGame.uuid,
      uuid: sGame.uuid,
      title: sGame.title || '',
      platform: sGame.platform || 'Домашний ПК',
      status: androidStatus,
      time: hours,
      rating: ratingStr,
      rating_grade: sGame.rating_grade || '',
      user_score: sGame.user_score || 0,
      note: sGame.user_review || sGame.notes || '',
      month: monthStr,
      year: yearStr,
      coverUrl: sGame.cover_url || sGame.background_url || '',
      avgPlaytime: sGame.playtime_main || null,
      rawg_id: sGame.rawg_id || null,
      slug: sGame.slug || '',
      genres: sGame.genres || '',
      developer: sGame.developer || '',
      publisher: sGame.publisher || '',
      is_favorite: sGame.is_favorite || 0,
      priority: sGame.priority || 'medium',
      created_at: sGame.created_at || '',
      updated_at: sGame.updated_at || ''
    };
  }

  function serverGameToAndroidWishlist(sGame) {
    let expYear = '2026';
    let expMonth = 'Апрель';
    if (sGame.release_date) {
      try {
        const d = new Date(sGame.release_date);
        if (!isNaN(d.getTime())) {
          expYear = d.getFullYear().toString();
          const months = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'];
          expMonth = months[d.getMonth()];
        }
      } catch (e) {}
    }

    return {
      id: sGame.uuid,
      uuid: sGame.uuid,
      title: sGame.title || '',
      platform: sGame.platform || 'Домашний ПК',
      expectedMonth: expMonth,
      expectedYear: expYear,
      note: sGame.notes || '',
      avgPlaytime: sGame.playtime_main || null,
      coverUrl: sGame.cover_url || '',
      rawg_id: sGame.rawg_id || null,
      updated_at: sGame.updated_at || '',
      created_at: sGame.created_at || ''
    };
  }

  // --- Network API Calls ---

  function cleanServerUrl(url) {
    if (!url) return '';
    let clean = url.trim();
    if (!/^https?:\/\//i.test(clean)) {
      clean = 'https://' + clean;
    }
    return clean.replace(/\/+$/, '');
  }

  async function checkServerStatus(serverUrl, syncToken) {
    const base = cleanServerUrl(serverUrl);
    if (!base) return { ok: false, error: 'NO_URL' };

    try {
      const res = await fetch(`${base}/api/sync/status`, {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${syncToken}`
        }
      });
      if (res.status === 401) {
        return { ok: false, error: 'UNAUTHORIZED', status: 401 };
      }
      if (!res.ok) {
        return { ok: false, error: res.statusText, status: res.status };
      }
      const data = await res.json();
      return { ok: true, data: data };
    } catch (e) {
      return { ok: false, error: e.message };
    }
  }

  async function performInitialSync(serverUrl, syncToken, currentGames, currentWishlist) {
    const base = cleanServerUrl(serverUrl);
    if (!base) throw new Error('Не указан URL сервера синхронизации');
    if (!syncToken) throw new Error('Не указан Sync Token');

    const clientId = getClientId();
    const nowIso = new Date().toISOString();

    // Prepare games payload with assigned UUIDs
    const gamesPayload = (currentGames || []).map(g => {
      if (!g.uuid) g.uuid = generateUuid();
      if (!g.updated_at) g.updated_at = nowIso;
      return g;
    });

    const wishlistPayload = (currentWishlist || []).map(w => {
      if (!w.uuid) w.uuid = generateUuid();
      if (!w.updated_at) w.updated_at = nowIso;
      return w;
    });

    const payload = {
      client_id: clientId,
      client_time_now: nowIso,
      games: gamesPayload,
      wishlist: wishlistPayload
    };

    const response = await fetch(`${base}/api/sync/initial`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${syncToken}`
      },
      body: JSON.stringify(payload)
    });

    if (response.status === 401) {
      throw new Error('Ошибка авторизации: неверный Sync Token');
    }
    if (!response.ok) {
      const errText = await response.text();
      throw new Error(`Ошибка Initial Sync (${response.status}): ${errText}`);
    }

    const data = await response.json();
    if (!data.success) {
      throw new Error(data.error || 'Initial sync failed');
    }

    // Split server master games into games and wishlist
    const newGames = [];
    const newWishlist = [];

    for (const sg of (data.games || [])) {
      if (sg.status === 'wishlist') {
        newWishlist.push(serverGameToAndroidWishlist(sg));
      } else {
        newGames.push(serverGameToAndroidGame(sg));
      }
    }

    // Save timestamp and clear queue
    localStorage.setItem(SYNC_STORAGE_KEYS.LAST_SYNC, data.server_time);
    clearSyncQueue();

    return {
      success: true,
      server_time: data.server_time,
      merged_count: data.merged_count,
      created_count: data.created_count,
      games: newGames,
      wishlist: newWishlist
    };
  }

  async function performDeltaSync(serverUrl, syncToken, currentGames, currentWishlist) {
    const base = cleanServerUrl(serverUrl);
    if (!base) throw new Error('Не указан URL сервера синхронизации');
    if (!syncToken) throw new Error('Не указан Sync Token');

    const lastSync = localStorage.getItem(SYNC_STORAGE_KEYS.LAST_SYNC) || '';
    if (!lastSync) {
      // No initial sync performed yet -> fallback to initial sync
      return await performInitialSync(serverUrl, syncToken, currentGames, currentWishlist);
    }

    const clientId = getClientId();
    const nowIso = new Date().toISOString();
    const queue = getSyncQueue();

    const changes = {
      created: [],
      updated: [],
      deleted: []
    };

    for (const qItem of queue) {
      if (qItem.action === 'create') {
        changes.created.push(Object.assign({}, qItem.payload, {
          uuid: qItem.uuid,
          client_seq: qItem.client_seq,
          updated_at: qItem.timestamp
        }));
      } else if (qItem.action === 'update') {
        changes.updated.push(Object.assign({}, qItem.payload, {
          uuid: qItem.uuid,
          client_seq: qItem.client_seq,
          updated_at: qItem.timestamp
        }));
      } else if (qItem.action === 'delete') {
        changes.deleted.push({
          uuid: qItem.uuid,
          deleted_at: qItem.timestamp,
          client_seq: qItem.client_seq
        });
      }
    }

    const syncReq = {
      client_id: clientId,
      client_version: '1.0',
      client_time_now: nowIso,
      last_sync_timestamp: lastSync,
      changes: changes
    };

    const response = await fetch(`${base}/api/sync`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${syncToken}`
      },
      body: JSON.stringify(syncReq)
    });

    if (response.status === 401) {
      throw new Error('Ошибка авторизации: неверный Sync Token');
    }
    if (!response.ok) {
      const errText = await response.text();
      throw new Error(`Ошибка Delta Sync (${response.status}): ${errText}`);
    }

    const resData = await response.json();
    if (!resData.success) {
      throw new Error(resData.error || 'Delta sync failed');
    }

    // 1. Remove applied actions from sync_queue
    const appliedUuids = [
      ...(resData.ack.applied_created || []),
      ...(resData.ack.applied_updated || []),
      ...(resData.ack.applied_deleted || [])
    ];
    removeAppliedFromQueue(appliedUuids);

    // 2. Apply server deletions
    let updatedGames = (currentGames || []).slice();
    let updatedWishlist = (currentWishlist || []).slice();

    const deletedUuids = new Set((resData.server_changes.deleted || []).map(d => d.uuid));
    if (deletedUuids.size > 0) {
      updatedGames = updatedGames.filter(g => !deletedUuids.has(g.uuid) && !deletedUuids.has(g.id));
      updatedWishlist = updatedWishlist.filter(w => !deletedUuids.has(w.uuid) && !deletedUuids.has(w.id));
    }

    // 3. Apply server created and updated games
    const serverItems = [
      ...(resData.server_changes.created || []),
      ...(resData.server_changes.updated || [])
    ];

    for (const sGame of serverItems) {
      if (!sGame.uuid) continue;

      if (sGame.status === 'wishlist') {
        // Belongs to wishlist
        const wItem = serverGameToAndroidWishlist(sGame);
        const idx = updatedWishlist.findIndex(w => w.uuid === sGame.uuid || w.id === sGame.uuid);
        if (idx >= 0) {
          updatedWishlist[idx] = Object.assign({}, updatedWishlist[idx], wItem);
        } else {
          updatedWishlist.push(wItem);
        }
        // Remove from games if it was moved to wishlist
        updatedGames = updatedGames.filter(g => g.uuid !== sGame.uuid && g.id !== sGame.uuid);
      } else {
        // Belongs to games
        const gItem = serverGameToAndroidGame(sGame);
        const idx = updatedGames.findIndex(g => g.uuid === sGame.uuid || g.id === sGame.uuid);
        if (idx >= 0) {
          updatedGames[idx] = Object.assign({}, updatedGames[idx], gItem);
        } else {
          updatedGames.unshift(gItem);
        }
        // Remove from wishlist if it was moved to games
        updatedWishlist = updatedWishlist.filter(w => w.uuid !== sGame.uuid && w.id !== sGame.uuid);
      }
    }

    // 4. Update last sync timestamp
    localStorage.setItem(SYNC_STORAGE_KEYS.LAST_SYNC, resData.server_time);

    return {
      success: true,
      server_time: resData.server_time,
      games: updatedGames,
      wishlist: updatedWishlist,
      applied_count: appliedUuids.length,
      server_created: (resData.server_changes.created || []).length,
      server_updated: (resData.server_changes.updated || []).length,
      server_deleted: (resData.server_changes.deleted || []).length
    };
  }

  // --- Auto-migration of local data (ensures existing items have UUIDs) ---
  function ensureLocalUuids(games, wishlist) {
    let changed = false;
    const nowIso = new Date().toISOString();

    const migratedGames = (games || []).map(g => {
      if (!g.uuid) {
        changed = true;
        return Object.assign({}, g, { uuid: generateUuid(), updated_at: g.updated_at || nowIso });
      }
      return g;
    });

    const migratedWishlist = (wishlist || []).map(w => {
      if (!w.uuid) {
        changed = true;
        return Object.assign({}, w, { uuid: generateUuid(), updated_at: w.updated_at || nowIso });
      }
      return w;
    });

    return { changed, games: migratedGames, wishlist: migratedWishlist };
  }

  // Export to global scope
  window.GameRoomSync = {
    KEYS: SYNC_STORAGE_KEYS,
    generateUuid: generateUuid,
    getClientId: getClientId,
    getSyncQueue: getSyncQueue,
    enqueueAction: enqueueAction,
    clearSyncQueue: clearSyncQueue,
    androidGameToSyncItem: androidGameToSyncItem,
    androidWishlistToSyncItem: androidWishlistToSyncItem,
    serverGameToAndroidGame: serverGameToAndroidGame,
    serverGameToAndroidWishlist: serverGameToAndroidWishlist,
    checkServerStatus: checkServerStatus,
    performInitialSync: performInitialSync,
    performDeltaSync: performDeltaSync,
    ensureLocalUuids: ensureLocalUuids
  };

})(window);
