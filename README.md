# Склад с pub/sub

Два асинхронных сервиса для складских операций:

- `inventory_api` — приём поступлений и расходов, расчёт остатков и аналитики, публикация событий в Redis.
- `analytics_worker` — подписка на Redis pub/sub, валидация событий и обновление агрегатов `stock_agg`.

Коммуникация: Redis pub/sub (`inventory.receipt`, `inventory.issue`).  
Хранилище: PostgreSQL. Запросы — SQLAlchemy Core поверх asyncpg (GROUP BY и вложенные подзапросы).

## Схема БД

- `stock_events` — журнал операций (поступление / расход).
- `stock_agg` — агрегированный остаток по паре `(warehouse, sku)`. Воркер **обновляет** существующую строку (`INSERT ... ON CONFLICT DO UPDATE`), не создаёт дубликаты пары.
- `processed_events` — идемпотентность воркера по `event_id`. Воркер догоняет `stock_events` при старте и каждые `CATCH_UP_INTERVAL_SEC` секунд, если pub/sub-сообщение потерялось.

Миграции: Alembic, `migrations/versions/001_initial.py` и `002_processed_events.py`.

## Запуск через Docker

```bash
docker compose up --build
```

API: http://localhost:8080  

Корневой URL показывает список эндпоинтов. Миграции запускаются при старте `inventory_api` (`alembic upgrade head`).

## Локальный запуск

Нужны Python >= 3.10, PostgreSQL и Redis.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
docker compose up -d postgres redis
alembic upgrade head
python -m inventory_api
python -m analytics_worker
```

Переменные окружения:

| Имя | По умолчанию |
| --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://warehouse:warehouse@localhost:5432/warehouse` |
| `REDIS_URL` | `redis://localhost:6379/0` |
| `API_HOST` | `0.0.0.0` |
| `API_PORT` | `8080` |
| `CATCH_UP_INTERVAL_SEC` | `2` |

## API

### `POST /receipts`

```json
{ "sku": "A-100", "qty": 50, "warehouse": "WH-1" }
```

Пишет операцию поступления и публикует `inventory.receipt`.

### `POST /issues`

```json
{ "sku": "A-100", "qty": 20, "warehouse": "WH-1" }
```

Пишет расход и публикует `inventory.issue`. Если остатка не хватает — `409`.

### `GET /stock?warehouse=WH-1&sku=A-100`

`sku` опционален. Остатки считаются из `stock_events` (GROUP BY + подзапрос).

### `GET /stock/summary?top_n=5`

- `warehouses[]`: `warehouse`, `total_qty`, `sku_count`
- `top_skus[]`: TOP-N SKU по суммарному остатку на всех складах

## Тесты

Тесты ходят в реальные PostgreSQL и Redis, но в **отдельную** БД `warehouse_test` и Redis DB `15`, чтобы не задевать запущенные сервисы.

```bash
docker compose up -d postgres redis
pytest
```

Тесты применяют Alembic к `warehouse_test`. Покрыто: операции и summary (GROUP BY / подзапросы), гонка расходов, миграции, идемпотентность воркера, catch-up потерянного pub/sub, обработка сообщения из Redis.
