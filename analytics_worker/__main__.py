import asyncio
import logging

from analytics_worker.worker import consume
from shared.db import create_engine
from shared.redis_client import create_redis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


async def run() -> None:
    engine = create_engine()
    redis = create_redis()
    try:
        await consume(redis, engine)
    finally:
        await redis.aclose()
        await engine.dispose()


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
