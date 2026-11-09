from __future__ import annotations

import json
import logging
from typing import Any

from aiohttp import ContentTypeError, web
from pydantic import ValidationError
from redis.asyncio import Redis
from sqlalchemy import insert, text
from sqlalchemy.ext.asyncio import AsyncEngine

from inventory_api.queries import (
    current_qty_query,
    stock_query,
    top_skus_query,
    warehouse_summary_query,
)
from shared.events import EventType, InventoryEvent
from shared.models import stock_events
from shared.redis_client import publish_event

ENGINE_KEY = web.AppKey("engine", AsyncEngine)
REDIS_KEY = web.AppKey("redis", Redis)
logger = logging.getLogger(__name__)


def _json_error(status: int, message: str) -> web.Response:
    return web.json_response({"error": message}, status=status)


async def _read_operation(
    request: web.Request, event_type: EventType
) -> InventoryEvent | web.Response:
    try:
        payload: dict[str, Any] = await request.json()
    except (json.JSONDecodeError, ContentTypeError):
        return _json_error(400, "invalid JSON")

    if not isinstance(payload, dict):
        return _json_error(400, "invalid payload: object expected")

    try:
        return InventoryEvent(
            event_type=event_type,
            sku=payload.get("sku", ""),
            qty=payload.get("qty"),
            warehouse=payload.get("warehouse", ""),
        )
    except (TypeError, ValueError, ValidationError) as exc:
        return _json_error(400, f"invalid payload: {exc}")


async def create_operation(request: web.Request, event_type: EventType) -> web.Response:
    parsed = await _read_operation(request, event_type)
    if isinstance(parsed, web.Response):
        return parsed

    engine = request.app[ENGINE_KEY]
    redis = request.app[REDIS_KEY]

    async with engine.begin() as conn:
        await conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:w), hashtext(:s))"),
            {"w": parsed.warehouse, "s": parsed.sku},
        )
        if parsed.event_type == "issue":
            current = await conn.scalar(
                current_qty_query(parsed.warehouse, parsed.sku)
            )
            if int(current or 0) < parsed.qty:
                return _json_error(409, "insufficient stock")

        result = await conn.execute(
            insert(stock_events)
            .values(
                event_id=parsed.event_id,
                sku=parsed.sku,
                qty=parsed.qty,
                warehouse=parsed.warehouse,
                event_type=parsed.event_type,
                created_at=parsed.created_at,
            )
            .returning(stock_events.c.id)
        )
        row_id = result.scalar_one()

    try:
        await publish_event(redis, parsed)
    except Exception:
        logger.exception(
            "redis publish failed for event_id=%s; worker catch_up will replay",
            parsed.event_id,
        )
    return web.json_response(
        {
            "id": row_id,
            "event_id": parsed.event_id,
            "sku": parsed.sku,
            "qty": parsed.qty,
            "warehouse": parsed.warehouse,
            "event_type": parsed.event_type,
        },
        status=201,
    )


async def create_receipt(request: web.Request) -> web.Response:
    return await create_operation(request, "receipt")


async def create_issue(request: web.Request) -> web.Response:
    return await create_operation(request, "issue")


async def get_stock(request: web.Request) -> web.Response:
    warehouse = request.query.get("warehouse", "").strip()
    sku = request.query.get("sku", "").strip() or None
    if not warehouse:
        return _json_error(400, "warehouse is required")

    engine = request.app[ENGINE_KEY]
    async with engine.connect() as conn:
        rows = (await conn.execute(stock_query(warehouse, sku))).mappings().all()

    return web.json_response(
        {
            "warehouse": warehouse,
            "sku": sku,
            "items": [{"sku": row["sku"], "qty": int(row["qty"])} for row in rows],
        }
    )


async def get_stock_summary(request: web.Request) -> web.Response:
    try:
        top_n = int(request.query.get("top_n", "5"))
    except ValueError:
        return _json_error(400, "top_n must be an integer")
    if top_n <= 0:
        return _json_error(400, "top_n must be > 0")

    engine = request.app[ENGINE_KEY]
    async with engine.connect() as conn:
        warehouses = (
            (await conn.execute(warehouse_summary_query())).mappings().all()
        )
        top_skus = (await conn.execute(top_skus_query(top_n))).mappings().all()

    return web.json_response(
        {
            "warehouses": [
                {
                    "warehouse": row["warehouse"],
                    "total_qty": int(row["total_qty"]),
                    "sku_count": int(row["sku_count"]),
                }
                for row in warehouses
            ],
            "top_skus": [
                {"sku": row["sku"], "total_qty": int(row["total_qty"])}
                for row in top_skus
            ],
        }
    )


async def health(request: web.Request) -> web.Response:
    try:
        async with request.app[ENGINE_KEY].connect() as conn:
            await conn.execute(text("SELECT 1"))
        await request.app[REDIS_KEY].ping()
    except Exception:
        logger.exception("health check failed")
        return web.json_response({"status": "error"}, status=503)
    return web.json_response({"status": "ok"})


_ENDPOINTS = {
    "POST /receipts": {"sku": "A-100", "qty": 50, "warehouse": "WH-1"},
    "POST /issues": {"sku": "A-100", "qty": 20, "warehouse": "WH-1"},
    "GET /stock": "?warehouse=WH-1&sku=A-100",
    "GET /stock/summary": "?top_n=5",
    "GET /health": None,
}


async def index(request: web.Request) -> web.Response:
    body = {"service": "inventory_api", "endpoints": _ENDPOINTS}
    accept = request.headers.get("Accept", "")
    if "text/html" in accept:
        lines = [
            "<html><body><h1>inventory_api</h1><ul>",
            "<li>POST /receipts</li>",
            "<li>POST /issues</li>",
            "<li>GET /stock?warehouse=WH-1</li>",
            "<li>GET /stock/summary?top_n=5</li>",
            "<li>GET /health</li>",
            "</ul></body></html>",
        ]
        return web.Response(text="\n".join(lines), content_type="text/html")
    return web.json_response(body)
