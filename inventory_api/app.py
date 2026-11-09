import logging

from aiohttp import web

from inventory_api.handlers import (
    ENGINE_KEY,
    REDIS_KEY,
    create_issue,
    create_receipt,
    get_stock,
    get_stock_summary,
    health,
    index,
)
from shared.db import create_engine
from shared.redis_client import create_redis

logger = logging.getLogger(__name__)


@web.middleware
async def error_middleware(request: web.Request, handler):
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception:
        logger.exception("unhandled error on %s %s", request.method, request.path)
        return web.json_response({"error": "internal error"}, status=500)


async def _on_startup(app: web.Application) -> None:
    app[ENGINE_KEY] = create_engine()
    app[REDIS_KEY] = create_redis()


async def _on_cleanup(app: web.Application) -> None:
    await app[REDIS_KEY].aclose()
    await app[ENGINE_KEY].dispose()


def create_app() -> web.Application:
    app = web.Application(middlewares=[error_middleware])
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_post("/receipts", create_receipt)
    app.router.add_post("/issues", create_issue)
    app.router.add_get("/stock", get_stock)
    app.router.add_get("/stock/summary", get_stock_summary)
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    return app
