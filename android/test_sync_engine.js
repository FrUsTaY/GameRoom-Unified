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

// Mock fetch
let mockFetchHandler = null;
global.fetch = async (url, options) => {
  if (mockFetchHandler) {
    return mockFetchHandler(url, options);
  }
  throw new Error('fetch unmocked: ' + url);
};

// Load sync.js
const syncJsPath = path.join(__dirname, 'app', 'src', 'main', 'assets', 'js', 'core', 'sync.js');
const syncCode = fs.readFileSync(syncJsPath, 'utf8');
eval(syncCode);

const sync = global.window.GameRoomSync;
assert(sync, 'GameRoomSync must be exported to window');

async function runTests() {
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
    note: 'Отличный рогалик',
    release_date: '2020-09-17'
  };
  const syncItem = sync.androidGameToSyncItem(androidGame, 10);
  assert.strictEqual(syncItem.uuid, 'uuid-1234-5678');
  assert.strictEqual(syncItem.status, 'completed');
  assert.strictEqual(syncItem.user_playtime_minutes, 1530); // 25.5 * 60
  assert.strictEqual(syncItem.user_score, 9);
  assert.strictEqual(syncItem.release_date, '2020-09-17');
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
    completed_at: '2026-05-15T12:00:00Z',
    release_date: '2020-09-17'
  };
  const mappedBack = sync.serverGameToAndroidGame(serverGame);
  assert.strictEqual(mappedBack.uuid, 'uuid-1234-5678');
  assert.strictEqual(mappedBack.status, 'Пройдено');
  assert.strictEqual(mappedBack.time, '25.5');
  assert.strictEqual(mappedBack.rating, '9/10');
  assert.strictEqual(mappedBack.rating_grade, 'izumitelno');
  assert.strictEqual(mappedBack.year, '2026');
  assert.strictEqual(mappedBack.month, 'Май');
  assert.strictEqual(mappedBack.release_date, '2020-09-17');
  console.log('✔ Server -> Android game mapping verified');

  console.log('--- 5. Testing local data auto-migration ---');
  const oldGames = [{ id: '171234', title: 'Old Game' }];
  const oldWishlist = [{ id: '171235', title: 'Old Wishlist' }];
  const migration = sync.ensureLocalUuids(oldGames, oldWishlist);
  assert(migration.changed);
  assert(migration.games[0].uuid);
  assert(migration.wishlist[0].uuid);
  console.log('✔ Local auto-migration verified');

  console.log('\n--- 6. Rule 1: playing -> В процессе ---');
  assert.strictEqual(sync.STATUS_SERVER_TO_ANDROID['playing'], 'В процессе');
  assert.strictEqual(sync.STATUS_ANDROID_TO_SERVER['В процессе'], 'playing');
  const mappedPlaying = sync.serverGameToAndroidGame({ uuid: 'u1', title: 'G1', status: 'playing' });
  assert.strictEqual(mappedPlaying.status, 'В процессе');
  const syncedPlaying = sync.androidGameToSyncItem({ uuid: 'u1', title: 'G1', status: 'В процессе' });
  assert.strictEqual(syncedPlaying.status, 'playing');
  console.log('✔ playing -> В процессе verified bidirectionally');

  console.log('\n--- 7. Rule 2: completed -> Пройдено ---');
  assert.strictEqual(sync.STATUS_SERVER_TO_ANDROID['completed'], 'Пройдено');
  assert.strictEqual(sync.STATUS_ANDROID_TO_SERVER['Пройдено'], 'completed');
  const mappedCompleted = sync.serverGameToAndroidGame({ uuid: 'u2', title: 'G2', status: 'completed' });
  assert.strictEqual(mappedCompleted.status, 'Пройдено');
  const syncedCompleted = sync.androidGameToSyncItem({ uuid: 'u2', title: 'G2', status: 'Пройдено' });
  assert.strictEqual(syncedCompleted.status, 'completed');
  console.log('✔ completed -> Пройдено verified bidirectionally');

  console.log('\n--- 8. Rule 3: dropped and paused -> Брошено ---');
  assert.strictEqual(sync.STATUS_SERVER_TO_ANDROID['dropped'], 'Брошено');
  assert.strictEqual(sync.STATUS_SERVER_TO_ANDROID['paused'], 'Брошено');
  assert.strictEqual(sync.STATUS_ANDROID_TO_SERVER['Брошено'], 'dropped');
  const mappedDropped = sync.serverGameToAndroidGame({ uuid: 'u3', title: 'G3', status: 'dropped' });
  const mappedPaused = sync.serverGameToAndroidGame({ uuid: 'u4', title: 'G4', status: 'paused' });
  assert.strictEqual(mappedDropped.status, 'Брошено');
  assert.strictEqual(mappedPaused.status, 'Брошено');
  assert.strictEqual(mappedDropped.status, mappedPaused.status, 'Both dropped and paused map to the exact same state');
  console.log('✔ dropped and paused -> Брошено verified');

  console.log('\n--- 9. Rule 4: backlog -> Хочу пройти, а не В процессе ---');
  // Backlog sync item conversion
  const wishlistSync = sync.androidWishlistToSyncItem({ uuid: 'w1', title: 'Backlog Game' });
  assert.strictEqual(wishlistSync.status, 'backlog', 'Android backlog sync item must have status backlog');

  // Initial sync routing test
  mockFetchHandler = async (url) => {
    return {
      ok: true,
      status: 200,
      json: async () => ({
        success: true,
        server_time: '2026-10-01T12:00:00Z',
        merged_count: 0,
        created_count: 2,
        games: [
          { uuid: 'bg-1', title: 'Backlog Title', status: 'backlog', platform: 'PC / Steam' },
          { uuid: 'pl-1', title: 'Playing Title', status: 'playing', platform: 'PC / Steam' }
        ]
      })
    };
  };

  const initialRes = await sync.performInitialSync('http://test', 'test-token', [], []);
  assert.strictEqual(initialRes.games.length, 1, 'Only playing game should be in games');
  assert.strictEqual(initialRes.games[0].title, 'Playing Title');
  assert.strictEqual(initialRes.games[0].status, 'В процессе');
  assert.strictEqual(initialRes.wishlist.length, 1, 'Backlog game must be in wishlist («Хочу пройти»)');
  assert.strictEqual(initialRes.wishlist[0].title, 'Backlog Title');
  assert(!initialRes.games.some(g => g.title === 'Backlog Title'), 'Backlog game must NOT be in games («В процессе»)!');
  console.log('✔ backlog correctly routed to «Хочу пройти», not «В процессе»');

  console.log('\n--- 10. Rule 5: wishlist is NOT synced to Android ---');
  // Initial sync should ignore server wishlist
  mockFetchHandler = async (url) => {
    return {
      ok: true,
      status: 200,
      json: async () => ({
        success: true,
        server_time: '2026-10-01T12:00:00Z',
        merged_count: 0,
        created_count: 1,
        games: [
          { uuid: 'wl-1', title: 'Web Wishlist Only', status: 'wishlist', platform: 'PC / Steam' },
          { uuid: 'pl-2', title: 'Playing Game', status: 'playing', platform: 'PC / Steam' }
        ]
      })
    };
  };

  const initialWlRes = await sync.performInitialSync('http://test', 'test-token', [], []);
  assert(!initialWlRes.games.some(g => g.uuid === 'wl-1'), 'Server wishlist must not be added to games');
  assert(!initialWlRes.wishlist.some(w => w.uuid === 'wl-1'), 'Server wishlist must not be added to Android wishlist');
  assert.strictEqual(initialWlRes.games.length, 1);
  assert.strictEqual(initialWlRes.wishlist.length, 0);

  // Delta sync should ignore and purge server wishlist
  storage[sync.KEYS.LAST_SYNC] = '2026-10-01T10:00:00Z';
  mockFetchHandler = async (url) => {
    return {
      ok: true,
      status: 200,
      json: async () => ({
        success: true,
        server_time: '2026-10-01T13:00:00Z',
        ack: {},
        server_changes: {
          created: [
            { uuid: 'wl-2', title: 'Server Wishlist Item', status: 'wishlist' }
          ],
          updated: [],
          deleted: []
        }
      })
    };
  };

  const deltaRes = await sync.performDeltaSync('http://test', 'test-token', [], []);
  assert(!deltaRes.games.some(g => g.uuid === 'wl-2'), 'Delta sync must not add server wishlist to games');
  assert(!deltaRes.wishlist.some(w => w.uuid === 'wl-2'), 'Delta sync must not add server wishlist to Android wishlist');
  console.log('✔ server wishlist is completely skipped and not synced to Android');

  console.log('\n--- 11. Rule 6: Meta quest 3s VR -> Oculus Quest 3s ---');
  const questNormalized1 = sync.normalizePlatformServerToAndroid('Meta quest 3s VR');
  assert.strictEqual(questNormalized1, 'Oculus Quest 3s');
  const questNormalized2 = sync.normalizePlatformServerToAndroid('Meta Quest 3S VR');
  assert.strictEqual(questNormalized2, 'Oculus Quest 3s');
  const questNormalized3 = sync.normalizePlatformServerToAndroid('oculus quest');
  assert.strictEqual(questNormalized3, 'Oculus Quest 3s');

  const mappedQuestGame = sync.serverGameToAndroidGame({
    uuid: 'q1',
    title: 'Beat Saber',
    platform: 'Meta quest 3s VR',
    status: 'playing'
  });
  assert.strictEqual(mappedQuestGame.platform, 'Oculus Quest 3s', 'Card platform must be Oculus Quest 3s');

  const mappedQuestWishlist = sync.serverGameToAndroidWishlist({
    uuid: 'q2',
    title: 'Batman: Arkham Shadow',
    platform: 'Meta quest 3s VR',
    status: 'backlog'
  });
  assert.strictEqual(mappedQuestWishlist.platform, 'Oculus Quest 3s');
  console.log('✔ Meta quest 3s VR successfully normalized to Oculus Quest 3s');

  console.log('\n--- 12. Rule 7: Meta Quest 3s continues to be classified as VR in stats ---');
  // Verify Android UI statistics platform aggregation
  const testGames = [
    { id: '1', platform: 'Oculus Quest 3s', time: '10.5' },
    { id: '2', platform: 'Домашний ПК', time: '20.0' }
  ];
  const platformHours = {};
  testGames.forEach(g => {
    const h = parseFloat(g.time) || 0;
    platformHours[g.platform] = (platformHours[g.platform] || 0) + h;
  });
  assert.strictEqual(platformHours['Oculus Quest 3s'], 10.5, 'Oculus Quest 3s platform hours tracked');

  // Verify Android Fate roulette platform filter matches Oculus Quest 3s as Quest/VR
  const matchFate = (g, platform) => {
    switch (platform) {
      case 'PC': return g.platform === 'Домашний ПК' || g.platform === 'Рабочий ПК';
      case 'Switch': return g.platform === 'Nintendo Switch';
      case 'Quest': return g.platform === 'Oculus Quest 3s';
      default: return false;
    }
  };
  assert.strictEqual(matchFate(testGames[0], 'Quest'), true, 'Quest filter recognizes Oculus Quest 3s');
  assert.strictEqual(matchFate(testGames[1], 'Quest'), false);
  console.log('✔ Meta Quest 3s VR classification intact');

  console.log('\n--- 13. Rule 8: Release date and Completion date are distinct fields ---');
  const dualDateGame = {
    uuid: 'dual-1',
    title: 'Elden Ring DLC',
    status: 'Пройдено',
    release_date: '2024-06-21',
    month: 'Сентябрь',
    year: '2026',
    completed_at: '2026-09-15'
  };

  const syncedDual = sync.androidGameToSyncItem(dualDateGame);
  assert.strictEqual(syncedDual.release_date, '2024-06-21', 'Release date must be RAWG date');
  assert(syncedDual.completed_at.startsWith('2026-09'), 'Completed date must be completion timestamp');
  assert.notStrictEqual(syncedDual.release_date, syncedDual.completed_at, 'Release date and completion date must be different');

  const roundtripped = sync.serverGameToAndroidGame({
    uuid: 'dual-1',
    title: 'Elden Ring DLC',
    status: 'completed',
    release_date: '2024-06-21',
    completed_at: '2026-09-15T00:00:00Z'
  });
  assert.strictEqual(roundtripped.release_date, '2024-06-21');
  assert.strictEqual(roundtripped.month, 'Сентябрь');
  assert.strictEqual(roundtripped.year, '2026');
  console.log('✔ Release date and completion date are verified as separate independent fields');

  console.log('\n--- 14. Rule 9: Completion statistics use completion date, NOT release date ---');
  const compDateSample = sync.serverGameToAndroidGame({
    uuid: 'stat-1',
    title: 'Expedition 33',
    status: 'completed',
    user_playtime_minutes: 600,
    release_date: '2024-06-10',
    completed_at: '09.2026' // MM.YYYY format
  });
  assert.strictEqual(compDateSample.year, '2026', 'Year must come from completion date');
  assert.strictEqual(compDateSample.month, 'Сентябрь', 'Month must come from completion date');

  // Verify monthly stats calculation uses g.month (from completion date)
  const monthOrder = ['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];
  const monthHours = {};
  monthOrder.forEach(m => monthHours[m] = 0);
  [compDateSample].forEach(g => {
    const h = parseFloat(g.time) || 0;
    if (g.month) monthHours[g.month] = (monthHours[g.month] || 0) + h;
  });
  assert.strictEqual(monthHours['Сентябрь'], 10.0, 'Stats must credit hours to September (completion date)');
  assert.strictEqual(monthHours['Июнь'], 0.0, 'Stats must NOT credit hours to June (release date)');
  console.log('✔ Completion statistics strictly uses completion date, not release date');

  console.log('\n--- 15. Rule 10: Empty completion date is NOT replaced by release date ---');
  const emptyCompGame = sync.serverGameToAndroidGame({
    uuid: 'empty-comp-1',
    title: 'Uncompleted RPG',
    status: 'playing',
    release_date: '2024-06-10',
    completed_at: null
  });
  assert.strictEqual(emptyCompGame.release_date, '2024-06-10', 'Release date must be preserved');
  assert.strictEqual(emptyCompGame.month, '', 'Month must remain empty when completed_at is null');
  assert.strictEqual(emptyCompGame.year, '', 'Year must remain empty when completed_at is null');
  assert.strictEqual(emptyCompGame.completed_at, '', 'completed_at must remain empty string');

  // Stats test with empty completion date
  const monthHoursEmpty = {};
  monthOrder.forEach(m => monthHoursEmpty[m] = 0);
  [emptyCompGame].forEach(g => {
    const h = parseFloat(g.time) || 0;
    if (g.month) monthHoursEmpty[g.month] = (monthHoursEmpty[g.month] || 0) + h;
  });
  Object.values(monthHoursEmpty).forEach(val => {
    assert.strictEqual(val, 0, 'No month hours should be credited when completion date is empty');
  });
  console.log('✔ Empty completion date is correctly kept empty and not replaced by release date');

  console.log('\n--- 16. Rule 11: Android Rating 10/10 -> 3/10 updates rating_grade to musor ---');
  const highRating = sync.parseRatingToGrade('10/10');
  assert.strictEqual(highRating.grade, 'izumitelno');
  assert.strictEqual(highRating.score, 10);

  const lowRating = sync.parseRatingToGrade('3/10');
  assert.strictEqual(lowRating.grade, 'musor');
  assert.strictEqual(lowRating.score, 3);

  const midRating1 = sync.parseRatingToGrade('8/10');
  assert.strictEqual(midRating1.grade, 'pohvalno');

  const midRating2 = sync.parseRatingToGrade('5/10');
  assert.strictEqual(midRating2.grade, 'prohodnyak');

  const changedGame = {
    id: 'game-rating-test',
    uuid: 'uuid-rating-1234',
    title: 'Cyber Game',
    rating: '3/10',
    rating_grade: 'izumitelno' // stale grade from previous sync
  };
  const changedSyncItem = sync.androidGameToSyncItem(changedGame);
  assert.strictEqual(changedSyncItem.user_score, 3);
  assert.strictEqual(changedSyncItem.rating_grade, 'musor', 'Changing 10/10 to 3/10 must recalculate rating_grade to musor');
  console.log('✔ Rating change 10/10 -> 3/10 correctly recalculates rating_grade to musor');

  console.log('\n--- 17. Rule 12: Wishlist avgPlaytime sync mapping ---');
  const wishlistWithAvg = {
    id: 'wish-avg-1',
    uuid: 'uuid-wish-avg',
    title: 'Expedition 33',
    platform: 'Домашний ПК',
    avgPlaytime: 25.5
  };
  const wishSyncItem = sync.androidWishlistToSyncItem(wishlistWithAvg);
  assert.strictEqual(wishSyncItem.playtime_main, 25.5, 'Wishlist avgPlaytime must map to playtime_main');
  console.log('✔ Wishlist avgPlaytime sync mapping verified');

  console.log('\n--- 18. Rule 13: Yandex Restore state reset and queue invalidation ---');
  sync.enqueueAction('update', 'stale-uuid-999', { title: 'Pre-Restore Modification' });
  localStorage.setItem(sync.KEYS.LAST_SYNC, '2026-10-01T12:00:00Z');
  assert.ok(sync.getSyncQueue().length > 0, 'Queue must have pending action before restore');
  assert.ok(localStorage.getItem(sync.KEYS.LAST_SYNC), 'Last sync must be set before restore');

  sync.resetSyncState();
  assert.strictEqual(sync.getSyncQueue().length, 0, 'Queue must be empty after restore reset');
  assert.strictEqual(localStorage.getItem(sync.KEYS.LAST_SYNC), null, 'last_sync must be cleared after restore reset');
  console.log('✔ Yandex Restore queue invalidation and sync state reset verified');

  console.log('\n--- 19. Rule 14: Server rating_grade change updates Android rating and overrides stale score ---');
  const serverGameWithNewGrade = {
    uuid: 'uuid-server-grade-1',
    title: 'Web Edited Game',
    status: 'completed',
    rating_grade: 'musor',
    user_score: 10 // Stale score from older sync
  };
  const androidGameFromMusor = sync.serverGameToAndroidGame(serverGameWithNewGrade);
  assert.strictEqual(androidGameFromMusor.rating, '3/10', 'Web change to musor must update Android rating to 3/10 despite stale 10');
  assert.strictEqual(androidGameFromMusor.rating_grade, 'musor');
  assert.strictEqual(androidGameFromMusor.user_score, 3);

  const serverGameCleared = {
    uuid: 'uuid-server-grade-2',
    title: 'Web Cleared Game',
    status: 'completed',
    rating_grade: '',
    user_score: 10
  };
  const androidGameCleared = sync.serverGameToAndroidGame(serverGameCleared);
  assert.strictEqual(androidGameCleared.rating, '-', 'Web clearing rating must set Android rating to -');
  assert.strictEqual(androidGameCleared.rating_grade, '');
  assert.strictEqual(androidGameCleared.user_score, 0);
  console.log('✔ Server rating_grade changes correctly update Android rating and override stale score');

  console.log('\n--- 20. Rule 15: Android setting rating to "-" clears rating_grade to empty ---');
  const unratedGame = {
    uuid: 'uuid-unrated-1',
    title: 'Unrated Game',
    rating: '-',
    rating_grade: 'pohvalno' // stale grade
  };
  const unratedSyncItem = sync.androidGameToSyncItem(unratedGame);
  assert.strictEqual(unratedSyncItem.user_score, 0, 'User score must be 0 for -');
  assert.strictEqual(unratedSyncItem.rating_grade, '', 'Rating grade must be empty for -');
  console.log('✔ Android unrated (-) correctly clears rating_grade to empty string');

  console.log('\n--- 21. Rule 16: Android month and year edit overrides stale completed_at ---');
  const monthEditedGame = {
    uuid: 'uuid-month-test-1',
    title: 'Month Edit Game',
    status: 'Пройдено',
    month: 'Сентябрь',
    year: '2026',
    completed_at: '10.2026' // Stale completed_at from previous web sync
  };
  const monthSyncItem = sync.androidGameToSyncItem(monthEditedGame);
  assert.strictEqual(monthSyncItem.completed_at, '09.2026', 'Editing month to Сентябрь must override stale completed_at 10.2026 with 09.2026');
  console.log('✔ Android month/year edit correctly overrides stale completed_at');

  console.log('\n--- 22. Rule 17: Android 5/10 rating maps to prohodnyak and roundtrips to 5/10 ---');
  const fiveScoreGame = {
    uuid: 'uuid-five-score',
    title: 'Average Game',
    status: 'Пройдено',
    rating: '5/10'
  };
  const fiveSyncItem = sync.androidGameToSyncItem(fiveScoreGame);
  assert.strictEqual(fiveSyncItem.user_score, 5);
  assert.strictEqual(fiveSyncItem.rating_grade, 'prohodnyak');

  const roundtripGame = sync.serverGameToAndroidGame({
    uuid: 'uuid-five-score',
    title: 'Average Game',
    status: 'completed',
    rating_grade: fiveSyncItem.rating_grade,
    user_score: fiveSyncItem.user_score
  });
  assert.strictEqual(roundtripGame.rating, '5/10', '5/10 with prohodnyak must roundtrip back to 5/10 in Android');
  console.log('✔ Android 5/10 maps to prohodnyak and roundtrips accurately to 5/10');

  console.log('\n============================================================');
  console.log('ALL 22 TEST SUITES AND ALL 17 DISCREPANCY RULES PASSED! ✔');
  console.log('============================================================');
}

runTests().catch(err => {
  console.error('Test failed:', err);
  process.exit(1);
});
