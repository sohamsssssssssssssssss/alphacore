from __future__ import annotations

import asyncio
import json
import struct
from datetime import datetime, timezone
from typing import Any

import asyncpg
from sqlalchemy import text

from data.db_models import create_tables, get_engine
from engines.ml.features import OrderBookFeatureEngine


class NSELiveFeed:
    """Ingest L2 ITCH-like updates, compute features, and persist snapshots."""

    # 1b type, 20b symbol, 1b side, 8b price, 4b qty, 8b ts_ns
    ITCH_STRUCT = struct.Struct(">c20scdIq")

    def __init__(self, db_url: str, feature_engine: OrderBookFeatureEngine):
        self.db_url = db_url
        self.feature_engine = feature_engine
        self._pool: asyncpg.Pool | None = None
        self._engine = get_engine(db_url)
        create_tables(self._engine)
        self._l2_state: dict[str, dict[str, dict[float, int]]] = {}
        self._buffer: list[dict[str, Any]] = []

    async def _ensure_pool(self) -> None:
        if self.db_url.startswith("postgresql") and self._pool is None:
            self._pool = await asyncpg.create_pool(dsn=self.db_url)

    async def connect(self, endpoint: str) -> None:
        host, port_str = endpoint.split(":", 1)
        reader, _writer = await asyncio.open_connection(host, int(port_str))
        while True:
            try:
                raw_msg = await reader.readexactly(self.ITCH_STRUCT.size)
            except asyncio.IncompleteReadError:
                break
            await self.on_l2_update(raw_msg)

    @classmethod
    def _parse_itch_message(cls, raw_msg: bytes) -> dict[str, Any]:
        _msg_type, symbol_raw, side_raw, price, qty, ts_ns = cls.ITCH_STRUCT.unpack(raw_msg)
        symbol = symbol_raw.decode("ascii", errors="ignore").strip().upper()
        side = side_raw.decode("ascii", errors="ignore").upper()
        ts = datetime.fromtimestamp(ts_ns / 1_000_000_000, tz=timezone.utc)
        return {
            "symbol": symbol,
            "side": side,
            "price": float(price),
            "qty": int(qty),
            "timestamp": ts,
            "timestamp_ns": int(ts_ns),
        }

    async def on_l2_update(self, raw_msg: bytes) -> None:
        msg = self._parse_itch_message(raw_msg)
        symbol = msg["symbol"]

        state = self._l2_state.setdefault(symbol, {"bids": {}, "asks": {}})
        side_key = "bids" if msg["side"] == "B" else "asks"
        side_map = state[side_key]

        if msg["qty"] <= 0:
            side_map.pop(msg["price"], None)
        else:
            side_map[msg["price"]] = msg["qty"]

        bids_sorted = sorted(state["bids"].items(), key=lambda x: x[0], reverse=True)[:5]
        asks_sorted = sorted(state["asks"].items(), key=lambda x: x[0])[:5]

        snapshot = {
            "bid_prices": [p for p, _q in bids_sorted] + [0.0] * (5 - len(bids_sorted)),
            "ask_prices": [p for p, _q in asks_sorted] + [0.0] * (5 - len(asks_sorted)),
            "bid_qtys": [float(q) for _p, q in bids_sorted] + [0.0] * (5 - len(bids_sorted)),
            "ask_qtys": [float(q) for _p, q in asks_sorted] + [0.0] * (5 - len(asks_sorted)),
            "last_price": float(msg["price"]),
            "volume": float(msg["qty"]),
            "timestamp_ns": msg["timestamp_ns"],
        }
        features = self.feature_engine.compute(snapshot)

        self._buffer.append(
            {
                "timestamp": msg["timestamp"],
                "symbol": symbol,
                "bids": [[float(p), int(q)] for p, q in bids_sorted],
                "asks": [[float(p), int(q)] for p, q in asks_sorted],
                "features": features,
            }
        )

    async def flush_to_db(self, batch_size: int = 1000) -> None:
        if not self._buffer:
            return

        rows = self._buffer[:batch_size]

        if self.db_url.startswith("postgresql"):
            await self._ensure_pool()
            assert self._pool is not None
            query = (
                "INSERT INTO order_book_snapshots (timestamp, symbol, bids, asks, features) "
                "VALUES ($1, $2, $3, $4, $5) "
                "ON CONFLICT (timestamp, symbol) DO NOTHING"
            )
            payload = [(r["timestamp"], r["symbol"], r["bids"], r["asks"], r["features"]) for r in rows]
            async with self._pool.acquire() as conn:
                await conn.executemany(query, payload)
        else:
            stmt = text(
                "INSERT OR IGNORE INTO order_book_snapshots "
                "(timestamp, symbol, bids, asks, features) "
                "VALUES (:timestamp, :symbol, :bids, :asks, :features)"
            )
            sqlite_rows = [
                {
                    "timestamp": r["timestamp"],
                    "symbol": r["symbol"],
                    "bids": json.dumps(r["bids"]),
                    "asks": json.dumps(r["asks"]),
                    "features": json.dumps(r["features"]),
                }
                for r in rows
            ]
            with self._engine.begin() as conn:
                conn.execute(stmt, sqlite_rows)

        del self._buffer[: len(rows)]

    def get_l2_state(self, symbol: str) -> dict:
        state = self._l2_state.get(symbol.upper(), {"bids": {}, "asks": {}})
        bids_sorted = sorted(state["bids"].items(), key=lambda x: x[0], reverse=True)[:5]
        asks_sorted = sorted(state["asks"].items(), key=lambda x: x[0])[:5]
        return {
            "bids": [[float(p), int(q)] for p, q in bids_sorted],
            "asks": [[float(p), int(q)] for p, q in asks_sorted],
        }


class SimulatedFeed(NSELiveFeed):
    def __init__(self, db_url: str, feature_engine: OrderBookFeatureEngine):
        super().__init__(db_url=db_url, feature_engine=feature_engine)

    async def run(self, n_messages: int = 10000) -> None:
        symbol = "RELIANCE"
        base_px = 2500.0
        ts_ns = 1_700_000_000_000_000_000
        batch_size = 1000

        for i in range(n_messages):
            side = b"B" if i % 2 == 0 else b"A"
            px_step = (i % 10) * 0.05
            price = base_px - px_step if side == b"B" else base_px + px_step
            qty = 100 + (i % 50)
            raw_msg = self.ITCH_STRUCT.pack(
                b"U",
                symbol.encode("ascii").ljust(20, b" "),
                side,
                float(price),
                int(qty),
                ts_ns + i,
            )
            await self.on_l2_update(raw_msg)
            if (i + 1) % batch_size == 0:
                await self.flush_to_db(batch_size=batch_size)

        while self._buffer:
            await self.flush_to_db(batch_size=batch_size)

        print(f"Simulated {n_messages} snapshots, flushed to DB")
