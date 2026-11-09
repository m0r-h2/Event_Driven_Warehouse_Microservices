from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from shared.config import database_url


def create_engine() -> AsyncEngine:
    return create_async_engine(database_url(), pool_pre_ping=True)
