from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from shared.events import InventoryEvent
from shared.models import processed_events, stock_agg, stock_events

logger = logging.getLogger(__name__)


async def apply_event(conn: AsyncConnection, event: InventoryEvent) -> bool:
    """Apply once per event_id; keep a single stock_agg row per (warehouse, sku)."""
    claimed = insert(processed_events).values(event_id=event.event_id)
    claimed = claimed.on_conflict_do_nothing().returning(processed_events.c.event_id)
    if await conn.scalar(claimed) is None:
        logger.info("skip duplicate event_id=%s", event.event_id)
        return False

    delta = event.signed_qty
    stmt = insert(stock_agg).values(
        warehouse=event.warehouse,
        sku=event.sku,
        qty=delta,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_stock_agg_warehouse_sku",
        set_={
            "qty": stock_agg.c.qty + stmt.excluded.qty,
            "updated_at": func.now(),
        },
    )
    await conn.execute(stmt)
    logger.info(
        "stock_agg updated warehouse=%s sku=%s delta=%s",
        event.warehouse,
        event.sku,
        delta,
    )
    return True


async def catch_up(engine: AsyncEngine) -> int:
    """Replay stock_events that never reached the worker (lost pub/sub)."""
    applied = 0
    async with engine.begin() as conn:
        pending = (
            select(stock_events)
            .where(
                stock_events.c.event_id.notin_(select(processed_events.c.event_id))
            )
            .order_by(stock_events.c.id)
        )
        rows = (await conn.execute(pending)).mappings().all()
        for row in rows:
            event = InventoryEvent(
                event_id=row["event_id"],
                event_type=row["event_type"],
                sku=row["sku"],
                qty=row["qty"],
                warehouse=row["warehouse"],
                created_at=row["created_at"],
            )
            if await apply_event(conn, event):
                applied += 1
    if applied:
        logger.info("catch_up applied %s events", applied)
    return applied
