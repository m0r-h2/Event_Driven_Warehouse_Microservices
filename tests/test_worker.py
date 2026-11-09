import asyncio

from sqlalchemy import func, insert, select

from analytics_worker.processor import apply_event, catch_up
from analytics_worker.worker import consume, handle_message
from inventory_api.queries import stock_query
from shared.events import InventoryEvent
from shared.models import stock_agg, stock_events
from shared.redis_client import publish_event


async def test_apply_event_updates_same_row(engine):
    event1 = InventoryEvent(
        event_type="receipt", sku="A-100", qty=50, warehouse="WH-1"
    )
    event2 = InventoryEvent(
        event_type="issue", sku="A-100", qty=20, warehouse="WH-1"
    )

    async with engine.begin() as conn:
        await apply_event(conn, event1)
        await apply_event(conn, event2)

    async with engine.connect() as conn:
        rows = (await conn.execute(select(stock_agg))).mappings().all()
        count = await conn.scalar(select(func.count()).select_from(stock_agg))

    assert count == 1
    assert rows[0]["warehouse"] == "WH-1"
    assert rows[0]["sku"] == "A-100"
    assert rows[0]["qty"] == 30


async def test_handle_message_validates_and_updates(engine):
    valid = InventoryEvent(
        event_type="receipt", sku="C-300", qty=7, warehouse="WH-3"
    )
    assert await handle_message(engine, valid.to_message()) is True
    assert await handle_message(engine, "{not-json") is False
    assert await handle_message(engine, '{"sku": "X", "qty": -1}') is False

    async with engine.connect() as conn:
        row = (
            await conn.execute(
                select(stock_agg).where(
                    stock_agg.c.warehouse == "WH-3",
                    stock_agg.c.sku == "C-300",
                )
            )
        ).mappings().one()
    assert row["qty"] == 7
    assert await handle_message(engine, valid.to_message()) is False
    async with engine.connect() as conn:
        qty = await conn.scalar(
            select(stock_agg.c.qty).where(
                stock_agg.c.warehouse == "WH-3",
                stock_agg.c.sku == "C-300",
            )
        )
    assert qty == 7


async def test_pubsub_message_updates_agg(engine, redis_client):
    event = InventoryEvent(
        event_type="receipt", sku="D-400", qty=11, warehouse="WH-4"
    )

    pubsub = redis_client.pubsub()
    await pubsub.subscribe(event.channel)

    async def _consume_one():
        async for message in pubsub.listen():
            if message.get("type") == "message":
                return await handle_message(engine, message["data"])

    task = asyncio.create_task(_consume_one())
    await asyncio.sleep(0.1)
    await publish_event(redis_client, event)
    handled = await asyncio.wait_for(task, timeout=3)
    await pubsub.aclose()
    assert handled is True

    async with engine.connect() as conn:
        qty = await conn.scalar(
            select(stock_agg.c.qty).where(
                stock_agg.c.warehouse == "WH-4",
                stock_agg.c.sku == "D-400",
            )
        )
    assert qty == 11


async def test_catch_up_matches_journal(engine):
    event = InventoryEvent(
        event_type="receipt", sku="E-500", qty=9, warehouse="WH-5"
    )
    async with engine.begin() as conn:
        await conn.execute(
            insert(stock_events).values(
                event_id=event.event_id,
                sku=event.sku,
                qty=event.qty,
                warehouse=event.warehouse,
                event_type=event.event_type,
                created_at=event.created_at,
            )
        )

    assert await catch_up(engine) == 1
    assert await catch_up(engine) == 0

    async with engine.connect() as conn:
        journal = (await conn.execute(stock_query("WH-5"))).mappings().one()
        agg = (
            await conn.execute(
                select(stock_agg.c.qty).where(
                    stock_agg.c.warehouse == "WH-5",
                    stock_agg.c.sku == "E-500",
                )
            )
        ).scalar_one()
    assert journal["qty"] == agg == 9


async def test_consume_catch_up_without_publish(engine, redis_client):
    event = InventoryEvent(
        event_type="receipt", sku="F-600", qty=3, warehouse="WH-6"
    )
    async with engine.begin() as conn:
        await conn.execute(
            insert(stock_events).values(
                event_id=event.event_id,
                sku=event.sku,
                qty=event.qty,
                warehouse=event.warehouse,
                event_type=event.event_type,
                created_at=event.created_at,
            )
        )

    stop = asyncio.Event()
    task = asyncio.create_task(consume(redis_client, engine, stop=stop))
    try:
        for _ in range(20):
            async with engine.connect() as conn:
                qty = await conn.scalar(
                    select(stock_agg.c.qty).where(
                        stock_agg.c.warehouse == "WH-6",
                        stock_agg.c.sku == "F-600",
                    )
                )
            if qty == 3:
                break
            await asyncio.sleep(0.1)
        else:
            raise AssertionError("worker catch_up did not apply unpublished event")
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=3)
