from redis.asyncio import Redis

from shared.config import redis_url
from shared.events import InventoryEvent


def create_redis() -> Redis:
    return Redis.from_url(redis_url(), decode_responses=True)


async def publish_event(client: Redis, event: InventoryEvent) -> None:
    await client.publish(event.channel, event.to_message())
