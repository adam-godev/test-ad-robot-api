# Keitaro API Client

Тестовое приложение для создания, синхронизации и редактирования кампаний Keitaro через Keitaro Admin API.

Проект состоит из backend API на FastAPI и frontend-интерфейса на Next.js. Приложение хранит локальную копию кампаний, streams и offers, позволяет подготовить изменения локально, а затем отправить их обратно в Keitaro через отдельный push.

## Основная логика

Приложение работает с кампанией, в которой есть два основных потока:

* `Flow 1` — отправляет выбранные GEO на `https://google.com`.
* `Flow 2` — fallback-поток с offers.

Для offers поддерживаются:

* добавление в stream;
* staged-удаление;
* восстановление удаленного из stream offer;
* автоматический перерасчет весов;
* закрепление offer weight через pin;
* отправка pending-изменений обратно в Keitaro.

## Как работает синхронизация

Приложение не применяет все изменения сразу в Keitaro. Сначала изменения сохраняются локально и получают `pending_action`, затем пользователь отдельно отправляет их через `Push to KT`.

Основной flow:

1. `Fetch from KT` загружает кампании из Keitaro в локальную БД.
2. При открытии кампании приложение подтягивает актуальные streams и offers.
3. Добавление, удаление или восстановление offer сначала применяется локально.
4. Изменения помечаются как pending.
5. `Push to KT` отправляет staged-изменения обратно в Keitaro.

Если offer был удален из stream в Keitaro, после refresh он помечается в приложении как `removed`. Такой offer можно восстановить локально, после чего `Push to KT` вернет его обратно в stream.

Важно: приложение восстанавливает привязку offer к stream, но не пересоздает сам offer entity в Keitaro, если он был полностью удален из Keitaro.

## Стек

* Backend: FastAPI, SQLAlchemy, Alembic, Poetry
* Frontend: TypeScript, Next.js
* Database: PostgreSQL
* Integration: Keitaro Admin API
* Runtime: Docker, Docker Compose

## Структура проекта

```text
backend/
  app/
    api/                 # FastAPI routes и dependencies
    integrations/keitaro # Keitaro API client и payload builders
    models.py            # SQLAlchemy-модели
    schemas.py           # Pydantic-схемы API
    services/            # Основная бизнес-логика

frontend/
  app/                   # Next.js routes
  components/            # UI-компоненты
  lib/                   # API-клиент и общие утилиты
```

Основная бизнес-логика кампаний, streams и offers находится в:

```text
backend/app/services/campaigns.py
```

## Требования

Для запуска через Docker:

* Docker
* Docker Compose

Для локального запуска без Docker:

* Python 3.12
* Poetry
* Node.js
* npm

## Переменные окружения

Создайте `.env` из примера:

```bash
cp .env.example .env
```

Основные переменные:

```env
# Публичный URL frontend. Backend использует его для CORS.
FRONTEND_URL=http://localhost:3000

# Публичный URL backend API, по которому браузер будет делать запросы.
# Если меняете значение, пересоберите frontend-образ.
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000

# Host-порты, которые Docker Compose пробрасывает наружу.
FRONTEND_PORT=3000
BACKEND_PORT=8000
POSTGRES_PORT=5432

# Настройки PostgreSQL-контейнера.
POSTGRES_DB=keitaro_test
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres

# URL базы для backend внутри Docker Compose сети.
DATABASE_URL=postgresql+psycopg://postgres:postgres@postgres:5432/keitaro_test

# URL Keitaro Admin API без /admin_api/v1.
KEITARO_BASE_URL=https://demo.keitaro.io

# API-ключ Keitaro. Используется только backend-сервисом.
KEITARO_API_KEY=replace-me

# Публичный tracking-домен для ссылок кампаний.
KEITARO_CAMPAIGN_DOMAIN_URL=https://tracker.example

# ID сущностей Keitaro, которые используются при создании новых кампаний.
KEITARO_DOMAIN_ID=1
KEITARO_GROUP_ID=1
KEITARO_TRAFFIC_SOURCE_ID=1
```

`KEITARO_BASE_URL` — адрес админки/API Keitaro без `/admin_api/v1`.

`KEITARO_CAMPAIGN_DOMAIN_URL` — публичный tracking-домен, из которого приложение строит ссылку кампании вида:

```text
https://tracker.example/{alias}
```

В production `KEITARO_CAMPAIGN_DOMAIN_URL` должен соответствовать домену с ID из `KEITARO_DOMAIN_ID`.

`FRONTEND_URL` и `NEXT_PUBLIC_API_BASE_URL` должны быть адресами, доступными из браузера. Например, если backend проброшен на `http://localhost:8080`, то `NEXT_PUBLIC_API_BASE_URL` тоже должен быть `http://localhost:8080`.

`DATABASE_URL` внутри Docker Compose должен указывать на service name `postgres`, а не на `localhost`. Внутри backend-контейнера `localhost` означает сам backend-контейнер.

Не добавляйте `KEITARO_API_KEY` в frontend-переменные с префиксом `NEXT_PUBLIC_`.

## Запуск через Docker

```bash
docker compose up --build
```

Docker Compose автоматически читает `.env`. Если переменные не заданы, используются стандартные значения:

* frontend: `http://localhost:3000`
* backend API: `http://localhost:8000`
* PostgreSQL host-port: `5432`
* backend database URL: `postgresql+psycopg://postgres:postgres@postgres:5432/keitaro_test`

Backend-контейнер автоматически выполняет миграции перед стартом Uvicorn.

Если нужно применить миграции вручную:

```bash
docker compose exec backend alembic upgrade head
```

Открыть после запуска:

* Frontend: `http://localhost:3000`
* Swagger UI: `http://localhost:8000/docs`

Если меняете `NEXT_PUBLIC_API_BASE_URL`, пересоберите frontend:

```bash
docker compose up --build frontend
```

## Локальный запуск

Backend:

```bash
cd backend
poetry install
poetry run alembic upgrade head
poetry run uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm ci
npm run dev
```

## Проверки

Backend-тесты в Docker:

```bash
docker compose exec backend pytest
```

Backend-тесты локально:

```bash
cd backend
poetry run pytest
```

Frontend-проверки локально:

```bash
cd frontend
npm run typecheck
npm run build
```

## Основной сценарий проверки

1. Откройте `http://localhost:3000/campaigns`.
2. Нажмите `Fetch from KT`, чтобы загрузить кампании из Keitaro.
3. Откройте кампанию кликом по карточке.
4. Проверьте, что отображаются stats, streams и offers.
5. Добавьте offer в offers-flow.
6. Проверьте, что веса пересчитались локально, а изменение помечено как pending.
7. Удалите offer из stream.
8. Проверьте, что offer не пушится сразу в Keitaro, а сначала получает pending-статус.
9. При необходимости закрепите offer, чтобы сохранить его weight при последующих пересчетах.
10. Нажмите `Push to KT`, чтобы отправить staged-изменения flow в Keitaro.

## API

Основные endpoints:

### Health

* `GET /api/health`

### Offers

* `GET /api/offers/search?q=miaflow&limit=20`

### Campaigns

* `POST /api/campaigns` — создать кампанию в Keitaro и локальной БД.
* `POST /api/campaigns/fetch-from-kt` — загрузить кампании из Keitaro.
* `GET /api/campaigns?limit=20&offset=0` — получить список локальных кампаний.
* `GET /api/campaigns/{id}?refresh=false` — получить кампанию; при `refresh=true` обновить данные из Keitaro.
* `POST /api/campaigns/{id}/stage-delete` — пометить кампанию на удаление.
* `POST /api/campaigns/{id}/restore` — отменить staged-удаление кампании.
* `POST /api/campaigns/push-to-kt` — отправить pending-удаления кампаний в Keitaro.
* `POST /api/campaigns/cancel-pending` — отменить pending-изменения кампаний.
* `GET /api/campaigns/{id}/stats?period=today` — получить stats кампании.

### Streams и offers

* `GET /api/campaigns/{id}/keitaro-streams`
* `POST /api/campaigns/{id}/streams/{flow_id}/offers`
* `POST /api/campaigns/{id}/streams/{flow_id}/offers/{offer_id}/stage-remove`
* `POST /api/campaigns/{id}/streams/{flow_id}/offers/{offer_id}/restore`
* `POST /api/campaigns/{id}/streams/{flow_id}/offers/{offer_id}/toggle-pin`
* `POST /api/campaigns/{id}/streams/push-to-kt`
* `POST /api/campaigns/{id}/streams/cancel-pending`
* `POST /api/campaigns/{id}/streams/{flow_id}/push-to-kt`
* `POST /api/campaigns/{id}/streams/{flow_id}/cancel-pending`

`POST /api/campaigns` поддерживает заголовок `Idempotency-Key`, чтобы безопасно повторять один и тот же запрос на создание кампании.

## Формат ошибок

Ошибки возвращаются в едином формате:

```json
{
  "error": {
    "code": "KEITARO_VALIDATION_ERROR",
    "message": "Keitaro rejected payload",
    "details": {}
  }
}
```

## Ограничения

* Приложение рассчитано на тестовый/умеренный объем данных.
* Backend для простоты использует синхронные запросы к Keitaro API.
* Pending-изменения применяются в Keitaro только после явного `Push to KT`.
