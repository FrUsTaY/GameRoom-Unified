// test_real_android_sync.js
// Comprehensive real HTTP end-to-end integration test runner between
// Android sync.js engine (in simulated WebView JS environment) and running FastAPI server.

const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const serverUrl = process.argv[2] || 'http://127.0.0.1:8089';
const syncToken = process.argv[3];

if (!syncToken) {
  console.error("Usage: node test_real_android_sync.js <serverUrl> <syncToken>");
  process.exit(1);
}

// Ensure direct test assertions on protected endpoints include the Bearer Sync Token
const originalFetch = globalThis.fetch;
globalThis.fetch = function(url, options = {}) {
  const opts = Object.assign({}, options);
  opts.headers = Object.assign({}, opts.headers);
  if (!opts.headers['Authorization'] && !opts.headers['authorization']) {
    opts.headers['Authorization'] = `Bearer ${syncToken}`;
  }
  return originalFetch(url, opts);
};

// 1. Factory to create isolated Android Client instances
function createAndroidClient(clientName = 'android-client-1') {
  const store = {};
  const mockLocalStorage = {
    getItem: (k) => (Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
    clear: () => { for (const k in store) delete store[k]; }
  };

  const sandbox = {
    window: {},
    localStorage: mockLocalStorage,
    fetch: globalThis.fetch,
    crypto: globalThis.crypto,
    console: console,
    Date: Date,
    Math: Math,
    JSON: JSON,
    Set: Set,
    Array: Array,
    Object: Object,
    String: String,
    parseInt: parseInt,
    parseFloat: parseFloat,
    isNaN: isNaN
  };
  sandbox.window = sandbox;

  const syncJsPath = path.join(__dirname, 'android', 'app', 'src', 'main', 'assets', 'js', 'core', 'sync.js');
  const syncJsCode = fs.readFileSync(syncJsPath, 'utf8');
  vm.createContext(sandbox);
  vm.runInContext(syncJsCode, sandbox);

  const engine = sandbox.GameRoomSync;
  assert.ok(engine, "GameRoomSync must be exported to window");

  return {
    name: clientName,
    engine: engine,
    localStorage: mockLocalStorage,
    games: [],
    wishlist: []
  };
}

async function runTests() {
  console.log("=================================================================");
  console.log(` Starting Real E2E Android ↔ Server Integration Test Matrix`);
  console.log(` Server URL : ${serverUrl}`);
  console.log(` Sync Token : ${syncToken.substring(0, 8)}...`);
  console.log("=================================================================\n");

  const client1 = createAndroidClient('Android-Device-Alpha');
  const engine = client1.engine;

  // -------------------------------------------------------------
  // Test 0: Server Status & Ping
  // -------------------------------------------------------------
  console.log("▶ [Test 0] Checking server ping & auth status via checkServerStatus...");
  const statusRes = await engine.checkServerStatus(serverUrl, syncToken);
  assert.strictEqual(statusRes.ok, true, `Ping failed: ${statusRes.error}`);
  assert.ok(statusRes.data.status === 'online' || statusRes.data.status === 'ok');
  console.log(`✔ Server ping OK! Games currently on server: ${statusRes.data.total_games}\n`);

  // -------------------------------------------------------------
  // Test 1: Initial Sync with local games & wishlist
  // -------------------------------------------------------------
  console.log("▶ [Test 1] Initial Sync (Android existing data ↔ Server DB safe merge)...");
  const localGame1 = {
    title: "Cyberpunk 2077: Phantom Liberty",
    platform: "Домашний ПК",
    status: "Пройдено",
    time: "45.5",
    rating: "9/10",
    note: "Невероятное дополнение!",
    avgPlaytime: 35
  };
  const localWishlist1 = {
    title: "Hollow Knight: Silksong",
    platform: "Домашний ПК",
    expectedYear: "2026",
    expectedMonth: "Декабрь",
    note: "Ждём релиз"
  };

  client1.games = [localGame1];
  client1.wishlist = [localWishlist1];

  const initRes = await engine.performInitialSync(serverUrl, syncToken, client1.games, client1.wishlist);
  assert.strictEqual(initRes.success, true);
  assert.ok(initRes.games.length >= 1, "Must have games returned");
  assert.ok(initRes.wishlist.length >= 1, "Must have wishlist items returned");

  // Verify UUIDs were created and saved in returned collections
  const mergedCyberpunk = initRes.games.find(g => g.title.includes("Cyberpunk"));
  assert.ok(mergedCyberpunk, "Cyberpunk must be in master games");
  assert.ok(mergedCyberpunk.uuid, "Must have assigned UUID");
  assert.strictEqual(mergedCyberpunk.status, "Пройдено");

  const mergedSilksong = initRes.wishlist.find(w => w.title.includes("Silksong"));
  assert.ok(mergedSilksong, "Silksong must be in master wishlist");
  assert.ok(mergedSilksong.uuid, "Silksong must have UUID");

  client1.games = initRes.games;
  client1.wishlist = initRes.wishlist;

  const lastSyncTs = client1.localStorage.getItem(engine.KEYS.LAST_SYNC);
  assert.ok(lastSyncTs, "Initial sync must store LAST_SYNC in localStorage");
  assert.strictEqual(engine.getSyncQueue().length, 0, "Queue must be empty after initial sync");
  console.log(`✔ Initial Sync passed! Master games count: ${client1.games.length}, wishlist: ${client1.wishlist.length}\n`);

  // -------------------------------------------------------------
  // Test 2: Repeated Sync without changes (Idempotency)
  // -------------------------------------------------------------
  console.log("▶ [Test 2] Repeated Delta Sync without changes (0 changes expected)...");
  const repeatRes = await engine.performDeltaSync(serverUrl, syncToken, client1.games, client1.wishlist);
  assert.strictEqual(repeatRes.success, true);
  assert.strictEqual(repeatRes.applied_count, 0, "No changes sent");
  assert.strictEqual(repeatRes.server_created, 0, "No new server games");
  assert.strictEqual(repeatRes.server_updated, 0, "No server updates");
  assert.strictEqual(repeatRes.server_deleted, 0, "No server deletions");
  console.log("✔ Repeated Sync passed! 0 changes exchanged, idempotency verified.\n");

  // -------------------------------------------------------------
  // Test 3: Android create → Server
  // -------------------------------------------------------------
  console.log("▶ [Test 3] Android creates new game → Delta Sync → Server...");
  const newGameUuid = engine.generateUuid();
  const createdGame = {
    id: newGameUuid,
    uuid: newGameUuid,
    title: "Elden Ring: Shadow of the Erdtree",
    platform: "PlayStation 5",
    status: "В процессе",
    time: "15.0",
    rating: "10/10",
    rating_grade: "izumitelno",
    user_score: 10,
    note: "Сложно, но великолепно!",
    month: "Октябрь",
    year: "2026",
    avgPlaytime: 40,
    updated_at: new Date().toISOString()
  };
  client1.games.unshift(createdGame);
  engine.enqueueAction('create', newGameUuid, engine.androidGameToSyncItem(createdGame));
  assert.strictEqual(engine.getSyncQueue().length, 1, "Queue must have 1 create action");

  const createSyncRes = await engine.performDeltaSync(serverUrl, syncToken, client1.games, client1.wishlist);
  assert.strictEqual(createSyncRes.success, true);
  assert.strictEqual(createSyncRes.applied_count, 1, "1 action applied");
  assert.strictEqual(engine.getSyncQueue().length, 0, "Queue must be empty after sync");

  // Direct fetch from server DB to verify exact storage
  const directServerFetch = await fetch(`${serverUrl}/api/games`);
  const serverGamesList = (await directServerFetch.json()).games;
  const serverElden = serverGamesList.find(g => g.uuid === newGameUuid);
  assert.ok(serverElden, "New game must exist in server database");
  assert.strictEqual(serverElden.title, "Elden Ring: Shadow of the Erdtree");
  assert.strictEqual(serverElden.status, "playing");
  assert.strictEqual(serverElden.user_playtime_minutes, 900); // 15h = 900 min
  assert.strictEqual(serverElden.rating_grade, "izumitelno");
  assert.strictEqual(serverElden.user_score, 10);
  console.log("✔ Android create → Server passed!\n");

  // -------------------------------------------------------------
  // Test 4: Android update → Server
  // -------------------------------------------------------------
  console.log("▶ [Test 4] Android updates game → Delta Sync → Server...");
  createdGame.time = "22.5";
  createdGame.note = "Победил Мессмера!";
  createdGame.status = "Пройдено";
  createdGame.updated_at = new Date().toISOString();

  engine.enqueueAction('update', newGameUuid, engine.androidGameToSyncItem(createdGame));
  const updateSyncRes = await engine.performDeltaSync(serverUrl, syncToken, client1.games, client1.wishlist);
  assert.strictEqual(updateSyncRes.success, true);
  assert.strictEqual(updateSyncRes.applied_count, 1);

  const directServerFetch2 = await fetch(`${serverUrl}/api/games`);
  const serverElden2 = (await directServerFetch2.json()).games.find(g => g.uuid === newGameUuid);
  assert.strictEqual(serverElden2.status, "completed");
  assert.strictEqual(serverElden2.user_playtime_minutes, 1350); // 22.5h = 1350m
  assert.strictEqual(serverElden2.notes, "Победил Мессмера!");
  console.log("✔ Android update → Server passed!\n");

  // -------------------------------------------------------------
  // Test 5: Server update → Android
  // -------------------------------------------------------------
  console.log("▶ [Test 5] Server modifies game → Android pulls change via Delta Sync...");
  // Update game on server simulating Web user action
  const serverPatchRes = await fetch(`${serverUrl}/api/games/${serverElden2.id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      notes: "Серверная заметка: пройдены все боссы!",
      user_review: "Серверная заметка: пройдены все боссы!",
      user_playtime_minutes: 1500, // 25 hours
      rating_grade: "izumitelno"
    })
  });
  assert.strictEqual(serverPatchRes.ok, true, "Server patch must succeed");

  const pullRes = await engine.performDeltaSync(serverUrl, syncToken, client1.games, client1.wishlist);
  assert.strictEqual(pullRes.success, true);
  assert.ok(pullRes.server_updated >= 1, "Must receive at least 1 server update");

  client1.games = pullRes.games;
  const androidUpdatedElden = client1.games.find(g => g.uuid === newGameUuid);
  assert.ok(androidUpdatedElden, "Game must remain in Android games");
  assert.strictEqual(androidUpdatedElden.note, "Серверная заметка: пройдены все боссы!");
  assert.strictEqual(androidUpdatedElden.time, "25.0");
  console.log("✔ Server update → Android passed!\n");

  // -------------------------------------------------------------
  // Test 6: Android offline queue with sequential changes & compaction
  // -------------------------------------------------------------
  console.log("▶ [Test 6] Android offline queue with compaction & sequential execution...");
  const offlineGameUuid = engine.generateUuid();
  const tempGameUuid = engine.generateUuid();

  // 1. Create offline game
  const offGame = {
    id: offlineGameUuid,
    uuid: offlineGameUuid,
    title: "Offline Adventure",
    platform: "PC",
    status: "В процессе",
    time: "2.0",
    rating: "7/10",
    note: "v1"
  };
  engine.enqueueAction('create', offlineGameUuid, engine.androidGameToSyncItem(offGame));

  // 2. Update offline game twice
  offGame.note = "v2";
  offGame.time = "3.5";
  engine.enqueueAction('update', offlineGameUuid, engine.androidGameToSyncItem(offGame));

  offGame.note = "v3 final";
  offGame.time = "5.0";
  engine.enqueueAction('update', offlineGameUuid, engine.androidGameToSyncItem(offGame));

  // 3. Create temp game and then delete it offline (should cancel out!)
  engine.enqueueAction('create', tempGameUuid, { title: "Cancel Me" });
  engine.enqueueAction('delete', tempGameUuid);

  const currentQueue = engine.getSyncQueue();
  assert.strictEqual(currentQueue.length, 1, "Queue compaction must keep only 1 action for offlineGameUuid");
  assert.strictEqual(currentQueue[0].action, 'create', "Initial create should be kept with merged payload");
  assert.strictEqual(currentQueue[0].payload.notes, "v3 final", "Payload must contain latest compacted note");
  assert.strictEqual(currentQueue[0].payload.user_playtime_minutes, 300, "5.0 hours = 300 minutes");

  client1.games.unshift(offGame);
  const offlineSyncRes = await engine.performDeltaSync(serverUrl, syncToken, client1.games, client1.wishlist);
  assert.strictEqual(offlineSyncRes.success, true);
  assert.strictEqual(offlineSyncRes.applied_count, 1);

  const checkOffGame = (await (await fetch(`${serverUrl}/api/games`)).json()).games.find(g => g.uuid === offlineGameUuid);
  assert.ok(checkOffGame, "Offline game must be created on server");
  assert.strictEqual(checkOffGame.notes, "v3 final");
  assert.strictEqual(checkOffGame.user_playtime_minutes, 300);

  const checkTempGame = (await (await fetch(`${serverUrl}/api/games`)).json()).games.find(g => g.uuid === tempGameUuid);
  assert.strictEqual(checkTempGame, undefined, "Canceled temp game must NEVER reach server");
  console.log("✔ Offline queue compaction and execution passed!\n");

  // -------------------------------------------------------------
  // Test 7: Delete → Tombstone → Another Client Sync
  // -------------------------------------------------------------
  console.log("▶ [Test 7] Delete → Tombstone → Multi-client propagation...");
  const client2 = createAndroidClient('Android-Device-Beta');
  // Initial sync client 2 so it knows about existing games
  const client2Init = await client2.engine.performInitialSync(serverUrl, syncToken, [], []);
  client2.games = client2Init.games;
  assert.ok(client2.games.some(g => g.uuid === offlineGameUuid), "Client 2 must have Offline Adventure");

  // Client 1 deletes offlineGameUuid
  client1.games = client1.games.filter(g => g.uuid !== offlineGameUuid);
  client1.engine.enqueueAction('delete', offlineGameUuid);
  const delSync1 = await client1.engine.performDeltaSync(serverUrl, syncToken, client1.games, client1.wishlist);
  assert.strictEqual(delSync1.success, true);
  assert.strictEqual(delSync1.applied_count, 1);

  // Client 2 syncs -> must receive server deletion tombstone!
  const client2Sync = await client2.engine.performDeltaSync(serverUrl, syncToken, client2.games, client2.wishlist);
  assert.strictEqual(client2Sync.success, true);
  assert.strictEqual(client2Sync.server_deleted, 1, "Client 2 must receive 1 deletion");
  assert.strictEqual(client2Sync.games.some(g => g.uuid === offlineGameUuid), false, "Game must be removed from Client 2");
  console.log("✔ Delete → Tombstone → Multi-client propagation passed!\n");

  // -------------------------------------------------------------
  // Test 8: Wishlist → Games with UUID Preservation
  // -------------------------------------------------------------
  console.log("▶ [Test 8] Wishlist item transferred to Games with UUID preservation...");
  const wishUuid = engine.generateUuid();
  const wishItem = {
    id: wishUuid,
    uuid: wishUuid,
    title: "Grand Theft Auto VI",
    platform: "PlayStation 5",
    expectedYear: "2026",
    expectedMonth: "Ноябрь",
    note: "Предзаказ"
  };
  client1.wishlist.push(wishItem);
  engine.enqueueAction('create', wishUuid, engine.androidWishlistToSyncItem(wishItem));

  const wishSync1 = await engine.performDeltaSync(serverUrl, syncToken, client1.games, client1.wishlist);
  assert.strictEqual(wishSync1.success, true);

  // Simulate Android UI: Transfer from wishlist to games
  const transferredGame = {
    id: wishUuid,
    uuid: wishUuid,
    title: "Grand Theft Auto VI",
    platform: "PlayStation 5",
    status: "В процессе",
    time: "1.0",
    rating: "8/10",
    rating_grade: "pohvalno",
    note: "Начал проходить!",
    month: "Ноябрь",
    year: "2026",
    avgPlaytime: null,
    updated_at: new Date().toISOString()
  };
  client1.wishlist = client1.wishlist.filter(w => w.uuid !== wishUuid);
  client1.games.unshift(transferredGame);
  engine.enqueueAction('update', wishUuid, engine.androidGameToSyncItem(transferredGame));

  const transSync = await engine.performDeltaSync(serverUrl, syncToken, client1.games, client1.wishlist);
  assert.strictEqual(transSync.success, true);
  assert.strictEqual(transSync.applied_count, 1);

  // Verify on server
  const serverGta = (await (await fetch(`${serverUrl}/api/games`)).json()).games.find(g => g.uuid === wishUuid);
  assert.ok(serverGta, "GTA VI must exist on server");
  assert.strictEqual(serverGta.uuid, wishUuid, "UUID must remain identical!");
  assert.strictEqual(serverGta.status, "playing", "Status must become 'playing' on server");
  assert.strictEqual(serverGta.user_playtime_minutes, 60);
  console.log("✔ Wishlist → Games transfer with UUID preservation passed!\n");

  // -------------------------------------------------------------
  // Test 9: Conflicting Changes (LWW Resolution)
  // -------------------------------------------------------------
  console.log("▶ [Test 9] Conflicting changes & Last-Write-Wins convergence...");
  // Server updates GTA VI at current time with a winning review
  await fetch(`${serverUrl}/api/games/${serverGta.id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      notes: "Серверная более свежая рецензия",
      user_review: "Серверная более свежая рецензия",
      user_playtime_minutes: 180,
      user_score: 9
    })
  });

  // Client 1 attempts to send an older change
  const oldTimestamp = new Date(Date.now() - 3600000).toISOString(); // 1 hour ago
  const stalePayload = engine.androidGameToSyncItem(transferredGame);
  stalePayload.notes = "Устаревшая клиентская заметка";
  stalePayload.updated_at = oldTimestamp;

  engine.enqueueAction('update', wishUuid, stalePayload);
  // Manually ensure the queued action timestamp is old
  const q = engine.getSyncQueue();
  q[0].timestamp = oldTimestamp;
  engine.saveSyncQueue?.(q) || client1.localStorage.setItem(engine.KEYS.SYNC_QUEUE, JSON.stringify(q));

  const conflictSync = await engine.performDeltaSync(serverUrl, syncToken, client1.games, client1.wishlist);
  assert.strictEqual(conflictSync.success, true);

  // Server record must maintain server note
  const serverGtaAfter = (await (await fetch(`${serverUrl}/api/games`)).json()).games.find(g => g.uuid === wishUuid);
  assert.strictEqual(serverGtaAfter.notes, "Серверная более свежая рецензия", "Server note must win LWW");

  // Client 1 must converge to winning server version
  client1.games = conflictSync.games;
  const client1Gta = client1.games.find(g => g.uuid === wishUuid);
  assert.strictEqual(client1Gta.note, "Серверная более свежая рецензия", "Client 1 must converge to winning server note");
  console.log("✔ Conflicting changes (LWW) and convergence passed!\n");

  // -------------------------------------------------------------
  // Test 10: Preservation of RAWG Metadata (Category B fields)
  // -------------------------------------------------------------
  console.log("▶ [Test 10] Preservation of RAWG metadata (Category B) during partial Android update...");
  // Enforce rich metadata on server game
  await fetch(`${serverUrl}/api/games/${serverGta.id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      rawg_id: 3498,
      genres: "Action, Open World, Crime",
      developer: "Rockstar Games",
      publisher: "Take-Two Interactive",
      rawg_rating: 4.8,
      metacritic: 97
    })
  });

  // Android client sends update with ONLY playtime and user score, with empty/undefined RAWG fields
  const partialGame = {
    uuid: wishUuid,
    title: "Grand Theft Auto VI",
    platform: "PlayStation 5",
    status: "Пройдено",
    time: "40.0",
    rating: "10/10",
    rating_grade: "izumitelno",
    note: "Прошёл всю сюжетную линию!",
    updated_at: new Date().toISOString()
  };
  engine.enqueueAction('update', wishUuid, engine.androidGameToSyncItem(partialGame));

  const rawgSync = await engine.performDeltaSync(serverUrl, syncToken, client1.games, client1.wishlist);
  assert.strictEqual(rawgSync.success, true);

  const serverGtaRawg = (await (await fetch(`${serverUrl}/api/games`)).json()).games.find(g => g.uuid === wishUuid);
  assert.strictEqual(serverGtaRawg.user_playtime_minutes, 2400); // 40h = 2400m
  assert.strictEqual(serverGtaRawg.rawg_id, 3498, "RAWG ID must be preserved");
  assert.strictEqual(serverGtaRawg.genres, "Action, Open World, Crime", "Genres must be preserved");
  assert.strictEqual(serverGtaRawg.developer, "Rockstar Games", "Developer must be preserved");
  assert.strictEqual(serverGtaRawg.publisher, "Take-Two Interactive", "Publisher must be preserved");
  assert.strictEqual(serverGtaRawg.metacritic, 97, "Metacritic must be preserved");
  console.log("✔ Preservation of RAWG metadata (Category B) passed!\n");

  // -------------------------------------------------------------
  // Test 11: Preservation of rating_grade (StopGame SVG rating)
  // -------------------------------------------------------------
  console.log("▶ [Test 11] Preservation of StopGame rating_grade across sync round-trip...");
  const gradeUuid = engine.generateUuid();
  const gradeGame = {
    id: gradeUuid,
    uuid: gradeUuid,
    title: "Black Myth: Wukong",
    platform: "PC",
    status: "Пройдено",
    time: "32.0",
    rating: "8/10",
    rating_grade: "pohvalno",
    user_score: 8,
    note: "Похвально от StopGame"
  };
  client1.games.unshift(gradeGame);
  engine.enqueueAction('create', gradeUuid, engine.androidGameToSyncItem(gradeGame));

  const gradeSync = await engine.performDeltaSync(serverUrl, syncToken, client1.games, client1.wishlist);
  assert.strictEqual(gradeSync.success, true);

  const serverWukong = (await (await fetch(`${serverUrl}/api/games`)).json()).games.find(g => g.uuid === gradeUuid);
  assert.strictEqual(serverWukong.rating_grade, "pohvalno", "Server must store 'pohvalno'");

  // Pull onto Client 2 and verify
  const client2WukongSync = await client2.engine.performDeltaSync(serverUrl, syncToken, client2.games, client2.wishlist);
  const client2Wukong = client2WukongSync.games.find(g => g.uuid === gradeUuid);
  assert.ok(client2Wukong, "Client 2 must receive Wukong");
  assert.strictEqual(client2Wukong.rating_grade, "pohvalno", "rating_grade must arrive intact on Client 2");
  console.log("✔ StopGame rating_grade preservation passed!\n");

  // -------------------------------------------------------------
  // Test 12: Stale delete CANNOT delete a newer updated record (LWW delete protection)
  // -------------------------------------------------------------
  console.log("▶ [Test 12] Stale delete cannot delete a newer updated record on server...");
  // Wukong was created and updated on server at current time
  const wukongServer = (await (await fetch(`${serverUrl}/api/games`)).json()).games.find(g => g.uuid === gradeUuid);
  assert.ok(wukongServer, "Wukong must exist on server");

  // Client attempts to send a stale deletion timestamped 1 hour ago
  const staleDeleteTime = new Date(Date.now() - 3600000).toISOString();
  client1.engine.enqueueAction('delete', gradeUuid);
  const qDel = client1.engine.getSyncQueue();
  const dAction = qDel.find(x => x.uuid === gradeUuid && x.action === 'delete');
  assert.ok(dAction, "Delete action must be in queue");
  dAction.timestamp = staleDeleteTime;
  client1.localStorage.setItem(client1.engine.KEYS.SYNC_QUEUE, JSON.stringify(qDel));

  const staleDelRes = await client1.engine.performDeltaSync(serverUrl, syncToken, client1.games, client1.wishlist);
  assert.strictEqual(staleDelRes.success, true);

  // Server record must STILL exist!
  const wukongServerAfter = (await (await fetch(`${serverUrl}/api/games`)).json()).games.find(g => g.uuid === gradeUuid);
  assert.ok(wukongServerAfter, "Wukong must NOT be deleted by stale delete!");

  // Client 1 must receive the surviving server record back
  const client1WukongSurvives = staleDelRes.games.find(g => g.uuid === gradeUuid);
  assert.ok(client1WukongSurvives, "Surviving game must be returned to client!");
  console.log("✔ Stale delete protection passed! Newer server update successfully defended against older delete.\n");

  // -------------------------------------------------------------
  // Test 13: Stale client update CANNOT resurrect a tombstone
  // -------------------------------------------------------------
  console.log("▶ [Test 13] Stale update cannot resurrect a tombstone on server...");
  // Now delete Wukong with CURRENT timestamp on server
  await fetch(`${serverUrl}/api/games/${wukongServer.id}`, { method: 'DELETE' });

  // Verify it is tombstoned on server
  const wukongGone = (await (await fetch(`${serverUrl}/api/games`)).json()).games.find(g => g.uuid === gradeUuid);
  assert.strictEqual(wukongGone, undefined, "Wukong must be deleted from server games table");

  // Client sends an older update for Wukong
  const staleWukongUpdate = Object.assign({}, gradeGame, {
    notes: "Попытка воскресить старым обновлением",
    updated_at: new Date(Date.now() - 60000).toISOString()
  });
  client1.engine.enqueueAction('update', gradeUuid, client1.engine.androidGameToSyncItem(staleWukongUpdate));

  const staleUpdRes = await client1.engine.performDeltaSync(serverUrl, syncToken, client1.games, client1.wishlist);
  assert.strictEqual(staleUpdRes.success, true);

  // Verify Wukong was NOT resurrected on server!
  const wukongStillGone = (await (await fetch(`${serverUrl}/api/games`)).json()).games.find(g => g.uuid === gradeUuid);
  assert.strictEqual(wukongStillGone, undefined, "Wukong must NOT be resurrected by stale update!");
  console.log("✔ Tombstone protection passed! Stale update did not resurrect deleted entity.\n");

  console.log("=================================================================");
  console.log(" 🎉 ALL 13 REAL INTEGRATION TEST SCENARIOS PASSED SUCCESSFULLY!");
  console.log("=================================================================");
}

runTests().catch(err => {
  console.error("\n❌ TEST RUNNER FAILURE:", err);
  process.exit(1);
});
