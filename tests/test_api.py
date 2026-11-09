import asyncio

from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql

from inventory_api.queries import stock_query, warehouse_summary_query
from shared.models import stock_events


async def test_receipt_writes_event_and_stock(api_client, engine, redis_client):
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("inventory.receipt")
    await pubsub.get_message(timeout=0.2)

    resp = await api_client.post(
        "/receipts",
        json={"sku": "A-100", "qty": 50, "warehouse": "WH-1"},
    )
    assert resp.status == 201
    body = await resp.json()
    assert body["sku"] == "A-100"
    assert body["qty"] == 50
    assert body["event_type"] == "receipt"

    stock = await api_client.get("/stock", params={"warehouse": "WH-1"})
    assert stock.status == 200
    payload = await stock.json()
    assert payload["items"] == [{"sku": "A-100", "qty": 50}]

    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=2)
    assert message is not None
    assert message["type"] == "message"
    await pubsub.aclose()

    async with engine.connect() as conn:
        count = await conn.scalar(select(func.count()).select_from(stock_events))
        compiled = str(
            stock_query("WH-1").compile(dialect=postgresql.dialect())
        ).upper()
        summary_sql = str(
            warehouse_summary_query().compile(dialect=postgresql.dialect())
        ).upper()
    assert count == 1
    assert "GROUP BY" in compiled
    assert "GROUP BY" in summary_sql
    assert "SKU_BALANCES" in compiled or "SKU_BALANCES" in summary_sql


async def test_issue_and_insufficient_stock(api_client):
    await api_client.post(
        "/receipts",
        json={"sku": "A-100", "qty": 20, "warehouse": "WH-1"},
    )
    ok = await api_client.post(
        "/issues",
        json={"sku": "A-100", "qty": 5, "warehouse": "WH-1"},
    )
    assert ok.status == 201

    stock = await (await api_client.get("/stock", params={"warehouse": "WH-1"})).json()
    assert stock["items"][0]["qty"] == 15

    conflict = await api_client.post(
        "/issues",
        json={"sku": "A-100", "qty": 100, "warehouse": "WH-1"},
    )
    assert conflict.status == 409


async def test_concurrent_issues_do_not_oversell(api_client):
    await api_client.post(
        "/receipts",
        json={"sku": "A-100", "qty": 50, "warehouse": "WH-1"},
    )
    first, second = await asyncio.gather(
        api_client.post("/issues", json={"sku": "A-100", "qty": 40, "warehouse": "WH-1"}),
        api_client.post("/issues", json={"sku": "A-100", "qty": 40, "warehouse": "WH-1"}),
    )
    statuses = sorted([first.status, second.status])
    assert statuses == [201, 409]
    stock = await (await api_client.get("/stock", params={"warehouse": "WH-1"})).json()
    assert stock["items"][0]["qty"] == 10


async def test_stock_summary_group_by_and_nested(api_client):
    ops = [
        ("/receipts", {"sku": "A-100", "qty": 50, "warehouse": "WH-1"}),
        ("/receipts", {"sku": "B-200", "qty": 10, "warehouse": "WH-1"}),
        ("/receipts", {"sku": "A-100", "qty": 30, "warehouse": "WH-2"}),
        ("/issues", {"sku": "A-100", "qty": 10, "warehouse": "WH-1"}),
        ("/receipts", {"sku": "C-300", "qty": 4, "warehouse": "WH-1"}),
        ("/issues", {"sku": "C-300", "qty": 4, "warehouse": "WH-1"}),
    ]
    for path, body in ops:
        resp = await api_client.post(path, json=body)
        assert resp.status == 201, await resp.text()

    summary = await api_client.get("/stock/summary", params={"top_n": 2})
    assert summary.status == 200
    data = await summary.json()

    by_wh = {row["warehouse"]: row for row in data["warehouses"]}
    assert by_wh["WH-1"]["total_qty"] == 50
    assert by_wh["WH-1"]["sku_count"] == 2
    assert by_wh["WH-2"]["total_qty"] == 30
    assert by_wh["WH-2"]["sku_count"] == 1
    assert "C-300" not in [row["sku"] for row in data["top_skus"]]

    assert [row["sku"] for row in data["top_skus"]] == ["A-100", "B-200"]
    assert data["top_skus"][0]["total_qty"] == 70
    assert len(data["top_skus"]) == 2


async def test_invalid_payload(api_client):
    resp = await api_client.post(
        "/receipts", json={"sku": "A-100", "qty": 0, "warehouse": "WH-1"}
    )
    assert resp.status == 400

    as_bool = await api_client.post(
        "/receipts", json={"sku": "A-100", "qty": True, "warehouse": "WH-1"}
    )
    assert as_bool.status == 400

    bad_json = await api_client.post(
        "/receipts",
        data="{",
        headers={"Content-Type": "application/json"},
    )
    assert bad_json.status == 400

    wrong_type = await api_client.post("/receipts", data=b"sku=A-100")
    assert wrong_type.status == 400


async def test_health(api_client):
    resp = await api_client.get("/health")
    assert resp.status == 200
    assert await resp.json() == {"status": "ok"}
