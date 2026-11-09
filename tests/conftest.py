from __future__ import annotations

import os
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from redis.asyncio import Redis
from sqlalchemy import create_engine as create_sync_engine
from sqlalchemy import text
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

os.environ["DATABASE_URL"] = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://warehouse:warehouse@localhost:5432/warehouse_test",
)
os.environ["REDIS_URL"] = os.getenv("TEST_REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("CATCH_UP_INTERVAL_SEC", "0.2")

from inventory_api.app import create_app
from inventory_api.handlers import ENGINE_KEY, REDIS_KEY
from shared.config import database_url, redis_url, require_ident

ROOT = Path(__file__).resolve().parents[1]
_migrated = False


def _ensure_test_database() -> None:
    url = make_url(database_url(sync=True))
    dbname = require_ident(url.database or "")
    admin = url.set(database="postgres")
    engine = create_sync_engine(admin, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"),
                {"n": dbname},
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    finally:
        engine.dispose()


def _upgrade_schema() -> None:
    global _migrated
    if _migrated:
        return
    sync_url = database_url(sync=True)
    engine = create_sync_engine(sync_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "DROP TABLE IF EXISTS processed_events, stock_agg, "
                "stock_events, alembic_version CASCADE"
            )
        )
    engine.dispose()
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", sync_url)
    command.upgrade(cfg, "head")
    _migrated = True


async def _can_connect_db() -> bool:
    try:
        _ensure_test_database()
        url = make_url(database_url(sync=True)).set(database="postgres")
        engine = create_sync_engine(url)
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        finally:
            engine.dispose()
    except Exception:
        return False


async def _can_connect_redis() -> bool:
    client = Redis.from_url(redis_url())
    try:
        return bool(await client.ping())
    except Exception:
        return False
    finally:
        await client.aclose()


@pytest_asyncio.fixture
async def require_infra():
    if not await _can_connect_db() or not await _can_connect_redis():
        pytest.skip(
            "Need PostgreSQL and Redis. Run: docker compose up -d postgres redis"
        )
    _upgrade_schema()


@pytest_asyncio.fixture
async def engine(require_infra) -> AsyncEngine:
    engine = create_async_engine(database_url(), pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE TABLE processed_events, stock_agg, stock_events "
                "RESTART IDENTITY CASCADE"
            )
        )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def redis_client(require_infra) -> Redis:
    client = Redis.from_url(redis_url(), decode_responses=True)
    await client.flushdb()
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def api_client(engine, redis_client, aiohttp_client):
    app = create_app()

    async def _startup_override(app):
        app[ENGINE_KEY] = engine
        app[REDIS_KEY] = redis_client

    async def _cleanup_override(app):
        return None

    app.on_startup.clear()
    app.on_cleanup.clear()
    app.on_startup.append(_startup_override)
    app.on_cleanup.append(_cleanup_override)
    return await aiohttp_client(app)
