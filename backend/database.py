"""Database configuration and table definitions for AlphaCore."""

from __future__ import annotations

from typing import Any

import databases
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from config import get_settings

settings = get_settings()
metadata = sa.MetaData()

order_book_snapshots = sa.Table(
    "order_book_snapshots",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("symbol", sa.String(length=20), nullable=False, index=True),
    sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
    sa.Column("bids", JSONB, nullable=False),
    sa.Column("asks", JSONB, nullable=False),
    sa.Column("spread", sa.Numeric(12, 4)),
    sa.Column("bid_ask_imbalance", sa.Numeric(8, 6)),
    sa.Column("total_bid_volume", sa.Numeric(18, 2)),
    sa.Column("total_ask_volume", sa.Numeric(18, 2)),
)

iceberg_detections = sa.Table(
    "iceberg_detections",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("symbol", sa.String(length=20), nullable=False, index=True),
    sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False, index=True),
    sa.Column("price_level", sa.Numeric(12, 4), nullable=False),
    sa.Column("visible_size", sa.Numeric(18, 2), nullable=False),
    sa.Column("estimated_hidden_volume", sa.Numeric(18, 2), nullable=False),
    sa.Column("refill_count", sa.Integer, nullable=False),
    sa.Column("direction", sa.String(length=10), nullable=False),
    sa.Column("confidence_score", sa.Integer, nullable=False),
    sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
    sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
)
sa.Index(
    "ix_iceberg_detections_symbol_detected_at_desc",
    iceberg_detections.c.symbol,
    iceberg_detections.c.detected_at.desc(),
)

spoof_detections = sa.Table(
    "spoof_detections",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("symbol", sa.String(length=20), nullable=False, index=True),
    sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False, index=True),
    sa.Column("order_price", sa.Numeric(12, 4), nullable=False),
    sa.Column("order_size", sa.Numeric(18, 2), nullable=False),
    sa.Column("spoof_score", sa.Integer, nullable=False),
    sa.Column("severity", sa.String(length=10), nullable=False),
    sa.Column("time_active_seconds", sa.Integer, nullable=False),
    sa.Column("price_impact", sa.Numeric(8, 4)),
    sa.Column("counter_trade_detected", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("check_refill_score", sa.Integer),
    sa.Column("check_cancel_speed_score", sa.Integer),
    sa.Column("check_fill_ratio_score", sa.Integer),
    sa.Column("check_price_impact_score", sa.Integer),
    sa.Column("check_counter_trade_score", sa.Integer),
)
sa.Index(
    "ix_spoof_detections_symbol_detected_at_desc",
    spoof_detections.c.symbol,
    spoof_detections.c.detected_at.desc(),
)

flow_imbalance_history = sa.Table(
    "flow_imbalance_history",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("symbol", sa.String(length=20), nullable=False, index=True),
    sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
    sa.Column("imbalance_score", sa.Numeric(6, 4), nullable=False),
    sa.Column("aggressive_buys", sa.Numeric(18, 2), nullable=False),
    sa.Column("aggressive_sells", sa.Numeric(18, 2), nullable=False),
    sa.Column("window_minutes", sa.Integer, nullable=False),
)

heatmap_matrix = sa.Table(
    "heatmap_matrix",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("symbol", sa.String(length=20), nullable=False, index=True),
    sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False, index=True),
    sa.Column("price_level", sa.Numeric(12, 4), nullable=False),
    sa.Column("bid_volume", sa.Numeric(18, 2), nullable=False),
    sa.Column("ask_volume", sa.Numeric(18, 2), nullable=False),
    sa.Column("total_volume", sa.Numeric(18, 2), nullable=False),
)
sa.Index(
    "ix_heatmap_matrix_symbol_snapshot_at_desc",
    heatmap_matrix.c.symbol,
    heatmap_matrix.c.snapshot_at.desc(),
)

narrative_signals = sa.Table(
    "narrative_signals",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("narrative", sa.String(length=100), nullable=False),
    sa.Column("confidence", sa.String(length=20), nullable=False),
    sa.Column("strength", sa.String(length=20)),
    sa.Column("regime", sa.String(length=50), nullable=False),
    sa.Column("started", sa.Date),
)

trade_signals = sa.Table(
    "trade_signals",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("symbol", sa.String(length=20), nullable=False),
    sa.Column("direction", sa.String(length=4), nullable=False),
    sa.Column("entry_price", sa.Numeric(12, 4), nullable=False),
    sa.Column("stop_loss", sa.Numeric(12, 4), nullable=False),
    sa.Column("target_price", sa.Numeric(12, 4), nullable=False),
    sa.Column("confidence", sa.Integer, nullable=False),
    sa.Column("score", sa.Integer, nullable=False),
    sa.Column("reasons", JSONB, nullable=False),
    sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
)
sa.Index(
    "ix_trade_signals_symbol_generated_at_desc",
    trade_signals.c.symbol,
    trade_signals.c.generated_at.desc(),
)

database = databases.Database(settings.DATABASE_URL)
async_engine: AsyncEngine = create_async_engine(settings.DATABASE_URL, future=True)


async def connect() -> None:
    """Open the shared database connection pool."""

    if not database.is_connected:
        await database.connect()


async def disconnect() -> None:
    """Close the shared database connection pool."""

    if database.is_connected:
        await database.disconnect()


def get_database() -> databases.Database:
    """Return the shared `databases` client instance."""

    return database


async def create_tables() -> None:
    """Create all database tables if they do not already exist."""

    async with async_engine.begin() as connection:
        await connection.run_sync(metadata.create_all)


async def ensure_trade_signals_table() -> None:
    """Ensure trade_signals table and index exist using direct SQL execution."""

    await database.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS trade_signals (
                id SERIAL PRIMARY KEY,
                symbol VARCHAR(20),
                direction VARCHAR(4),
                entry_price NUMERIC(12,4),
                stop_loss NUMERIC(12,4),
                target_price NUMERIC(12,4),
                confidence INTEGER,
                score INTEGER,
                reasons JSONB,
                generated_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
    )
    await database.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS ix_trade_signals_symbol_generated_at_desc
            ON trade_signals (symbol, generated_at DESC)
            """
        )
    )


async def ping_database() -> bool:
    """Return whether the configured database is reachable."""

    try:
        await database.fetch_one(sa.text("SELECT 1"))
        return True
    except Exception:
        return False


def serialize_levels(levels: list[Any]) -> list[dict[str, float]]:
    """Convert Pydantic order levels into JSON-serializable dictionaries."""

    return [level.model_dump() if hasattr(level, "model_dump") else dict(level) for level in levels]
