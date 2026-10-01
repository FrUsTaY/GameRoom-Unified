# Спецификация API синхронизации Game-Room (JSON-контракты)

## 1. Заголовки авторизации
Все защищённые запросы синхронизации требуют заголовок:
`Authorization: Bearer <gameroom_sync_token>`
или заголовок:
`X-Gameroom-Token: <gameroom_sync_token>`

---

## 2. Эндпоинты

### `GET /api/health`
Публичный эндпоинт проверки работоспособности (для Docker HEALTHCHECK):
```json
{
  "status": "ok"
}
```

### `GET /api/sync/status`
Проверка соединения и авторизации клиентом:
**Ответ (200 OK):**
```json
{
  "status": "online",
  "server_time": "2026-10-01T10:00:00.000000+00:00",
  "total_games": 42,
  "sync_protocol_version": "1.0"
}
```
**Ответ при неверном токене:** `401 Unauthorized`.

---

### `POST /api/sync/initial`
Первичное безопасное слияние баз данных.
**Запрос:**
```json
{
  "client_id": "android-a1b2c3d4",
  "client_time_now": "2026-10-01T10:00:00.000Z",
  "games": [
    {
      "uuid": "0f377b9a-4619-46e0-92bb-e70ed17f8eec",
      "title": "Cyberpunk 2077",
      "platform": "PC",
      "status": "Пройдено",
      "time": "45.0",
      "rating": "9/10",
      "note": "Отличная игра",
      "updated_at": "2026-10-01T09:30:00.000Z"
    }
  ],
  "wishlist": [
    {
      "uuid": "1e2f3a4b-5c6d-7e8f-9a0b-1c2d3e4f5a6b",
      "title": "Hollow Knight: Silksong",
      "platform": "PC",
      "expectedYear": "2026",
      "note": "Ждём",
      "updated_at": "2026-10-01T09:30:00.000Z"
    }
  ]
}
```
**Ответ (200 OK):**
```json
{
  "success": true,
  "server_time": "2026-10-01T10:00:01.000000+00:00",
  "client_id": "android-a1b2c3d4",
  "merged_count": 1,
  "created_count": 1,
  "games": [ ... master list of all games and wishlist ... ]
}
```

---

### `POST /api/sync`
Инкрементальная дельта-синхронизация.
**Запрос:**
```json
{
  "client_id": "android-a1b2c3d4",
  "client_version": "1.0",
  "client_time_now": "2026-10-01T10:05:00.000Z",
  "last_sync_timestamp": "2026-10-01T10:00:01.000000+00:00",
  "changes": {
    "created": [
      {
        "uuid": "2a3b4c5d-6e7f-8a9b-0c1d-2e3f4a5b6c7d",
        "client_seq": 1,
        "title": "Elden Ring",
        "status": "playing",
        "platform": "PC",
        "user_playtime_minutes": 120,
        "rating_grade": "izumitelno",
        "user_score": 10,
        "notes": "Потрясающе",
        "updated_at": "2026-10-01T10:02:00.000Z"
      }
    ],
    "updated": [
      {
        "uuid": "0f377b9a-4619-46e0-92bb-e70ed17f8eec",
        "client_seq": 2,
        "title": "Cyberpunk 2077",
        "status": "completed",
        "platform": "PC",
        "user_playtime_minutes": 3000,
        "notes": "Пройдено на 100%",
        "updated_at": "2026-10-01T10:04:00.000Z"
      }
    ],
    "deleted": [
      {
        "uuid": "3b4c5d6e-7f8a-9b0c-1d2e-3f4a5b6c7d8e",
        "client_seq": 3,
        "deleted_at": "2026-10-01T10:03:00.000Z"
      }
    ]
  }
}
```
**Ответ (200 OK):**
```json
{
  "success": true,
  "server_time": "2026-10-01T10:05:01.000000+00:00",
  "client_id": "android-a1b2c3d4",
  "ack": {
    "applied_created": ["2a3b4c5d-6e7f-8a9b-0c1d-2e3f4a5b6c7d"],
    "applied_updated": ["0f377b9a-4619-46e0-92bb-e70ed17f8eec"],
    "applied_deleted": ["3b4c5d6e-7f8a-9b0c-1d2e-3f4a5b6c7d8e"],
    "conflicts_resolved": 0
  },
  "server_changes": {
    "created": [],
    "updated": [],
    "deleted": []
  }
}
```
