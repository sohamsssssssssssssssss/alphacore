from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from data.nse_pipeline import NSELiveFeed
from engines.ml.features import OrderBookFeatureEngine


def _msg(symbol: str, side: bytes, price: float, qty: int, ts_ns: int) -> bytes:
    return NSELiveFeed.ITCH_STRUCT.pack(
        b"U",
        symbol.encode("ascii").ljust(20, b" "),
        side,
        float(price),
        int(qty),
        int(ts_ns),
    )


@pytest.mark.asyncio
async def test_parse_l2_update():
    feed = NSELiveFeed("sqlite+pysqlite:///:memory:", OrderBookFeatureEngine(use_cpp=False))

    ts0 = 1_700_000_000_000_000_000
    messages = [
        _msg("RELIANCE", b"B", 100.0, 10, ts0 + 1),
        _msg("RELIANCE", b"B", 99.5, 15, ts0 + 2),
        _msg("RELIANCE", b"B", 99.0, 20, ts0 + 3),
        _msg("RELIANCE", b"A", 100.5, 12, ts0 + 4),
        _msg("RELIANCE", b"A", 101.0, 18, ts0 + 5),
        _msg("RELIANCE", b"A", 101.5, 22, ts0 + 6),
        _msg("RELIANCE", b"B", 100.0, 11, ts0 + 7),
        _msg("RELIANCE", b"A", 100.5, 0, ts0 + 8),
        _msg("RELIANCE", b"B", 98.5, 30, ts0 + 9),
        _msg("RELIANCE", b"A", 102.0, 25, ts0 + 10),
    ]

    for msg in messages:
        await feed.on_l2_update(msg)

    state = feed.get_l2_state("RELIANCE")
    assert state["bids"] == [[100.0, 11], [99.5, 15], [99.0, 20], [98.5, 30]]
    assert state["asks"] == [[101.0, 18], [101.5, 22], [102.0, 25]]


@pytest.mark.asyncio
async def test_flush_to_db():
    feed = NSELiveFeed("sqlite+pysqlite:///:memory:", OrderBookFeatureEngine(use_cpp=False))

    base_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(1000):
        rows.append(
            {
                "timestamp": base_ts.replace(microsecond=i),
                "symbol": "RELIANCE",
                "bids": [[100.0, 10]],
                "asks": [[100.5, 12]],
                "features": {"f": float(i)},
            }
        )

    feed._buffer.extend(rows)
    await feed.flush_to_db(batch_size=1000)

    with feed._engine.connect() as conn:
        count1 = conn.execute(text("SELECT COUNT(*) FROM order_book_snapshots")).scalar_one()
    assert count1 == 1000

    feed._buffer.extend(rows)
    await feed.flush_to_db(batch_size=1000)

    with feed._engine.connect() as conn:
        count2 = conn.execute(text("SELECT COUNT(*) FROM order_book_snapshots")).scalar_one()
    assert count2 == 1000
