// test_sync_engine.js - Unit tests for Android client sync engine
const assert = require('assert');
const fs = require('fs');
const path = require('path');

// Mock localStorage
const storage = {};
global.localStorage = {
  getItem: (k) => storage[k] || null,
  setItem: (k, v) => { storage[k] = String(v); },
  removeItem: (k) => { delete storage[k]; },
  clear: () => { Object.keys(storage).forEach(k => delete storage[k]); }
};

// Mock window and crypto
global.window = global;
if (!global.crypto) {
  const { webcrypto } = require('crypto');
  global.crypto = webcrypto;
}

// Load sync.js
const syncJsPath = path.join(__dirname, 'app', 'src', 'main', 'assets', 'js', 'core', 'sync.js');
const syncCode = fs.readFileSync(syncJsPath, 'utf8');
eval(syncCode);

const sync = global.window.GameRoomSync;
assert(sync, 'GameRoomSync must be exported to window');

console.log('--- 1. Testing UUID generator ---');
const u1 = sync.generateUuid();
const u2 = sync.generateUuid();
assert.strictEqual(typeof u1, 'string');
assert.strictEqual(u1.length, 36);
assert.notStrictEqual(u1, u2);
console.log('✔ UUID generated:', u1);

console.log('--- 2. Testing Client ID generation ---');
const cid = sync.getClientId();
assert(cid.startsWith('android-'), 'Client ID must start with android-');
assert.strictEqual(sync.getClientId(), cid, 'Client ID must be persistent');
console.log('✔ Client ID:', cid);

console.log('--- 3. Testing sync_queue compaction ---');
sync.clearSyncQueue();
const testUuid = sync.generateUuid();

// Action 1: Create
sync.enqueueAction('create', testUuid, { title: 'Game A', status: 'playing' });
let q = sync.getSyncQueue();
assert.strictEqual(q.length, 1);
assert.strictEqual(q[0].action, 'create');
assert.strictEqual(q[0].payload.title, 'Game A');

// Action 2: Offline update (should merge into create)
sync.enqueueAction('update', testUuid, { time: '5.0', rating: '9/10' });
q = sync.getSyncQueue();
assert.strictEqual(q.length, 1, 'Should stay 1 compacted entry');
assert.strictEqual(q[0].action, 'create');
assert.strictEqual(q[0].payload.rating, '9/10');
assert.strictEqual(q[0].payload.time, '5.0');

// Action 3: Offline delete (should cancel out create)
sync.enqueueAction('delete', testUuid);
q = sync.getSyncQueue();
assert.strictEqual(q.length, 0, 'Create + Delete offline must cancel out completely');
console.log('✔ Offline queue compaction verified');

console.log('--- 4. Testing entity mappings ---');
const androidGame = {
  id: 'game-123',
  uuid: 'uuid-1234-5678',
  title: 'Hades',
  platform: 'Домашний ПК',
  status: 'Пройдено',
  time: '25.5',
  rating: '9/10',
  note: 'Отличный рогалик'
};
const syncItem = sync.androidGameToSyncItem(androidGame, 10);
assert.strictEqual(syncItem.uuid, 'uuid-1234-5678');
assert.strictEqual(syncItem.status, 'completed');
assert.strictEqual(syncItem.user_playtime_minutes, 1530); // 25.5 * 60
assert.strictEqual(syncItem.user_score, 9);
console.log('✔ Android -> Server game mapping verified');

// Server -> Android mapping
const serverGame = {
  uuid: 'uuid-1234-5678',
  title: 'Hades',
  platform: 'PC',
  status: 'completed',
  user_playtime_minutes: 1530,
  user_score: 9,
  rating_grade: 'izumitelno',
  user_review: 'Отличный рогалик',
  completed_at: '2026-05-15T12:00:00Z'
};
const mappedBack = sync.serverGameToAndroidGame(serverGame);
assert.strictEqual(mappedBack.uuid, 'uuid-1234-5678');
assert.strictEqual(mappedBack.status, 'Пройдено');
assert.strictEqual(mappedBack.time, '25.5');
assert.strictEqual(mappedBack.rating, '9/10');
assert.strictEqual(mappedBack.rating_grade, 'izumitelno');
assert.strictEqual(mappedBack.year, '2026');
assert.strictEqual(mappedBack.month, 'Май');
console.log('✔ Server -> Android game mapping verified');

console.log('--- 5. Testing local data auto-migration ---');
const oldGames = [{ id: '171234', title: 'Old Game' }];
const oldWishlist = [{ id: '171235', title: 'Old Wishlist' }];
const migration = sync.ensureLocalUuids(oldGames, oldWishlist);
assert(migration.changed);
assert(migration.games[0].uuid);
assert(migration.wishlist[0].uuid);
console.log('✔ Local auto-migration verified');

console.log('\n========================================');
console.log('ALL ANDROID SYNC ENGINE TESTS PASSED! ✔');
console.log('========================================');
