import sqlalchemy as sa

metadata = sa.MetaData()

stock_events = sa.Table(
    "stock_events",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("event_id", sa.String(36), nullable=False, unique=True),
    sa.Column("sku", sa.String(64), nullable=False),
    sa.Column("qty", sa.Integer, nullable=False),
    sa.Column("warehouse", sa.String(64), nullable=False),
    sa.Column("event_type", sa.String(16), nullable=False),
    sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.CheckConstraint("qty > 0", name="ck_stock_events_qty_positive"),
    sa.CheckConstraint(
        "event_type IN ('receipt', 'issue')",
        name="ck_stock_events_type",
    ),
    sa.Index("ix_stock_events_warehouse_sku", "warehouse", "sku"),
)

stock_agg = sa.Table(
    "stock_agg",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("warehouse", sa.String(64), nullable=False),
    sa.Column("sku", sa.String(64), nullable=False),
    sa.Column("qty", sa.Integer, nullable=False, server_default="0"),
    sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.UniqueConstraint("warehouse", "sku", name="uq_stock_agg_warehouse_sku"),
)

processed_events = sa.Table(
    "processed_events",
    metadata,
    sa.Column("event_id", sa.String(36), primary_key=True),
    sa.Column(
        "processed_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
)