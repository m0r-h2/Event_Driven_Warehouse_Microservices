from sqlalchemy import Select, case, func, select
from sqlalchemy.sql.selectable import Subquery

from shared.models import stock_events

signed_qty = case(
    (stock_events.c.event_type == "receipt", stock_events.c.qty),
    else_=-stock_events.c.qty,
)


def sku_balances() -> Subquery:
    """Per warehouse+sku remainder. Nested into summary/stock queries."""
    return (
        select(
            stock_events.c.warehouse,
            stock_events.c.sku,
            func.sum(signed_qty).label("qty"),
        )
        .group_by(stock_events.c.warehouse, stock_events.c.sku)
        .subquery("sku_balances")
    )


def stock_query(warehouse: str, sku: str | None = None) -> Select:
    balances = sku_balances()
    stmt = select(balances.c.sku, balances.c.qty).where(
        balances.c.warehouse == warehouse
    )
    if sku:
        stmt = stmt.where(balances.c.sku == sku)
    return stmt.order_by(balances.c.sku)


def current_qty_query(warehouse: str, sku: str) -> Select:
    return (
        select(func.coalesce(func.sum(signed_qty), 0))
        .where(stock_events.c.warehouse == warehouse)
        .where(stock_events.c.sku == sku)
    )


def warehouse_summary_query() -> Select:
    balances = sku_balances()
    return (
        select(
            balances.c.warehouse,
            func.sum(balances.c.qty).label("total_qty"),
            func.count(balances.c.sku).label("sku_count"),
        )
        .where(balances.c.qty != 0)
        .group_by(balances.c.warehouse)
        .order_by(balances.c.warehouse)
    )


def top_skus_query(top_n: int) -> Select:
    balances = sku_balances()
    ranked = (
        select(
            balances.c.sku,
            func.sum(balances.c.qty).label("total_qty"),
        )
        .group_by(balances.c.sku)
        .subquery("sku_totals")
    )
    return (
        select(ranked.c.sku, ranked.c.total_qty)
        .where(ranked.c.total_qty != 0)
        .order_by(ranked.c.total_qty.desc(), ranked.c.sku)
        .limit(top_n)
    )
