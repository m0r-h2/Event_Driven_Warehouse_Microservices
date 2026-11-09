from __future__ import annotations

import asyncio
import logging
import time

from pydantic import ValidationError
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from analytics_worker.processor import apply_event, catch_up
from shared.config import catch_up_interval_sec
from shared.events import CHANNELS, InventoryEvent

logger = logging.getLogger(__name__)


async def handle_message(engine: AsyncEngine, payload: str | bytes) -> bool:
    try:
        event = InventoryEvent.from_message(payload)
    except (ValidationError, ValueError, TypeError) as exc:
        logger.warning("skip invalid event: %s", exc)
        return False

    async with engine.begin() as conn:
        return await apply_event(conn, event)


async def consume(
    redis: Redis,
    engine: AsyncEngine,
    stop: asyncio.Event | None = None,
) -> None:
    interval = catch_up_interval_sec()
    while stop is None or not stop.is_set():
        pubsub = redis.pubsub()
        try:
            await catch_up(engine)
            await pubsub.subscribe(*CHANNELS)
            logger.info("subscribed to %s", ", ".join(CHANNELS))
            last_catch_up = time.monotonic()
            while stop is None or not stop.is_set():
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=0.2
                )
                if (
                    message
                    and message.get("type") == "message"
                    and message.get("data") is not None
                ):
                    try:
                        await handle_message(engine, message["data"])
                    except Exception:
                        logger.exception("failed to process pub/sub message")
                now = time.monotonic()
                if now - last_catch_up >= interval:
                    await catch_up(engine)
                    last_catch_up = now
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("pubsub loop failed, reconnecting")
            await asyncio.sleep(1)
        finally:
            try:
                await pubsub.unsubscribe(*CHANNELS)
            except Exception:
                logger.debug("unsubscribe failed", exc_info=True)
            await pubsub.aclose()
