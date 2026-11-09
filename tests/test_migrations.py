from sqlalchemy import text


async def test_alembic_head_applied(engine):
    async with engine.connect() as conn:
        version = await conn.scalar(text("SELECT version_num FROM alembic_version"))
        events = await conn.scalar(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'stock_events'"
            )
        )
        agg = await conn.scalar(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'stock_agg'"
            )
        )
        processed = await conn.scalar(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'processed_events'"
            )
        )
    assert version == "002"
    assert events == 1
    assert agg == 1
    assert processed == 1
