import os
import re

_DB_NAME = re.compile(r"^[A-Za-z0-9_]+$")


def database_url(*, sync: bool = False) -> str:
    url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://warehouse:warehouse@localhost:5432/warehouse",
    )
    if sync:
        return (
            url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
            .replace("postgresql+psycopg://", "postgresql+psycopg2://")
            .replace("postgresql://", "postgresql+psycopg2://")
        )
    return url


def redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


def api_host() -> str:
    return os.getenv("API_HOST", "0.0.0.0")


def api_port() -> int:
    return int(os.getenv("API_PORT", "8080"))


def catch_up_interval_sec() -> float:
    return float(os.getenv("CATCH_UP_INTERVAL_SEC", "2"))


def require_ident(name: str) -> str:
    if not _DB_NAME.match(name):
        raise ValueError(f"invalid identifier: {name!r}")
    return name
