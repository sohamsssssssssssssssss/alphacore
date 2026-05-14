"""In-memory state manager for AlphaCore order book data."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from database import (
    flow_imbalance_history,
    get_database,
    heatmap_matrix,
    iceberg_detections,
    spoof_detections,
)
from engines.flow_engine import flow_engine
from engines.heatmap_engine import heatmap_engine
from engines.iceberg_detector import iceberg_detector
from engines.spoof_detector import spoof_detector
from fastapi import WebSocket

from models.schemas import FlowImbalance, IcebergDetection, OrderBookSnapshot, SpoofDetection

logger = logging.getLogger(__name__)


class OrderBookStateManager:
    """Hold the latest and recent historical order book snapshots in memory."""

    def __init__(self, history_limit: int = 120) -> None:
        """Initialize the state manager."""

        self._snapshots: dict[str, OrderBookSnapshot] = {}
        self._history: dict[str, deque[OrderBookSnapshot]] = defaultdict(
            lambda: deque(maxlen=history_limit)
        )
        self._last_update: dict[str, datetime] = {}
        self._connected_websockets: set[WebSocket] = set()
        self._subscriptions: dict[WebSocket, str] = {}
        self.history_limit = history_limit

    def configure_history_limit(self, history_limit: int) -> None:
        """Reconfigure the retained snapshot history length."""

        self.history_limit = history_limit
        existing_history = {
            symbol: deque(snapshots, maxlen=history_limit)
            for symbol, snapshots in self._history.items()
        }
        self._history = defaultdict(lambda: deque(maxlen=history_limit), existing_history)

    async def update(self, symbol: str, snapshot: OrderBookSnapshot) -> None:
        """Store a new snapshot, update history, and broadcast it."""

        normalized_symbol = symbol.upper()
        self._snapshots[normalized_symbol] = snapshot
        self._history[normalized_symbol].append(snapshot)
        self._last_update[normalized_symbol] = snapshot.timestamp

        flow_result = flow_engine.update(normalized_symbol, snapshot)
        iceberg_results = iceberg_detector.update(normalized_symbol, snapshot)
        spoof_results = spoof_detector.update(normalized_symbol, snapshot)
        heatmap_engine.update(normalized_symbol, snapshot)
        asyncio.create_task(
            self._persist_detections(
                normalized_symbol,
                snapshot,
                flow_result,
                iceberg_results,
                spoof_results,
            )
        )

        await self.broadcast(normalized_symbol, snapshot)

    def get_latest(self, symbol: str) -> OrderBookSnapshot | None:
        """Return the latest snapshot for a symbol if available."""

        return self._snapshots.get(symbol.upper())

    def get_history(self, symbol: str, minutes: int) -> list[OrderBookSnapshot]:
        """Return snapshots for a symbol within the requested time window."""

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        return [
            snapshot
            for snapshot in self._history.get(symbol.upper(), deque())
            if snapshot.timestamp >= cutoff
        ]

    def get_active_symbols(self) -> list[str]:
        """Return all symbols with an in-memory latest snapshot."""

        return sorted(self._snapshots.keys())

    def get_last_update(self, symbol: str) -> datetime | None:
        """Return the last update timestamp for a symbol."""

        return self._last_update.get(symbol.upper())

    def get_last_fetch_time(self) -> datetime | None:
        """Return the most recent snapshot timestamp across all symbols."""

        if not self._last_update:
            return None
        return max(self._last_update.values())

    def add_websocket(self, ws: WebSocket, symbol: str) -> None:
        """Register a new websocket subscriber for a specific symbol."""

        self._connected_websockets.add(ws)
        self._subscriptions[ws] = symbol.upper()

    def remove_websocket(self, ws: WebSocket) -> None:
        """Remove a websocket subscriber gracefully."""

        self._connected_websockets.discard(ws)
        self._subscriptions.pop(ws, None)

    async def broadcast(self, symbol: str, snapshot: OrderBookSnapshot) -> None:
        """Send a snapshot update to all subscribed websocket clients."""

        stale_connections: list[WebSocket] = []
        payload = {
            "type": "orderbook_update",
            "symbol": snapshot.symbol,
            "timestamp": snapshot.timestamp.isoformat(),
            "bids": [level.model_dump() for level in snapshot.bids],
            "asks": [level.model_dump() for level in snapshot.asks],
            "spread": snapshot.spread,
            "bid_ask_imbalance": snapshot.bid_ask_imbalance,
            "total_bid_volume": snapshot.total_bid_volume,
            "total_ask_volume": snapshot.total_ask_volume,
        }

        for ws in list(self._connected_websockets):
            if self._subscriptions.get(ws) != symbol.upper():
                continue
            try:
                await ws.send_json(payload)
            except Exception as exc:
                logger.info("Removing disconnected websocket for %s: %s", symbol, exc)
                stale_connections.append(ws)

        for ws in stale_connections:
            self.remove_websocket(ws)

    async def _persist_detections(
        self,
        symbol: str,
        snapshot: OrderBookSnapshot,
        flow_result: FlowImbalance | None,
        iceberg_results: list[IcebergDetection],
        spoof_results: list[SpoofDetection],
    ) -> None:
        """Persist engine outputs asynchronously without blocking state updates."""

        try:
            database = get_database()
            if flow_result is not None:
                await database.execute(
                    flow_imbalance_history.insert().values(
                        symbol=flow_result.symbol,
                        timestamp=flow_result.timestamp,
                        imbalance_score=flow_result.imbalance_score,
                        aggressive_buys=flow_result.aggressive_buys,
                        aggressive_sells=flow_result.aggressive_sells,
                        window_minutes=flow_result.window_minutes,
                    )
                )

                flow_5min = flow_engine.get_flow_window(symbol, 5)
                if flow_5min is not None:
                    await database.execute(
                        flow_imbalance_history.insert().values(
                            symbol=flow_5min.symbol,
                            timestamp=flow_5min.timestamp,
                            imbalance_score=flow_5min.imbalance_score,
                            aggressive_buys=flow_5min.aggressive_buys,
                            aggressive_sells=flow_5min.aggressive_sells,
                            window_minutes=flow_5min.window_minutes,
                        )
                    )

            for detection in iceberg_results:
                await database.execute(
                    iceberg_detections.insert().values(
                        symbol=detection.symbol,
                        detected_at=detection.detected_at,
                        price_level=detection.price_level,
                        visible_size=detection.visible_size,
                        estimated_hidden_volume=detection.estimated_hidden_volume,
                        refill_count=detection.refill_count,
                        direction=detection.direction,
                        confidence_score=detection.confidence_score,
                        is_active=detection.is_active,
                        last_seen_at=detection.last_seen_at,
                    )
                )

            for detection in spoof_results:
                await database.execute(
                    spoof_detections.insert().values(
                        symbol=detection.symbol,
                        detected_at=detection.detected_at,
                        order_price=detection.order_price,
                        order_size=detection.order_size,
                        spoof_score=detection.spoof_score,
                        severity=detection.severity,
                        time_active_seconds=detection.time_active_seconds,
                        price_impact=detection.price_impact,
                        counter_trade_detected=detection.counter_trade_detected,
                        check_refill_score=detection.check_refill_score,
                        check_cancel_speed_score=detection.check_cancel_speed_score,
                        check_fill_ratio_score=detection.check_fill_ratio_score,
                        check_price_impact_score=detection.check_price_impact_score,
                        check_counter_trade_score=detection.check_counter_trade_score,
                    )
                )

            bid_map = {level.price: level.volume for level in snapshot.bids}
            ask_map = {level.price: level.volume for level in snapshot.asks}
            for price_level in sorted(set(bid_map) | set(ask_map)):
                bid_volume = float(bid_map.get(price_level, 0.0))
                ask_volume = float(ask_map.get(price_level, 0.0))
                await database.execute(
                    heatmap_matrix.insert().values(
                        symbol=symbol,
                        snapshot_at=snapshot.timestamp,
                        price_level=price_level,
                        bid_volume=bid_volume,
                        ask_volume=ask_volume,
                        total_volume=bid_volume + ask_volume,
                    )
                )
        except Exception as exc:
            logger.error("Failed to persist detections for %s: %s", symbol, exc)


state_manager = OrderBookStateManager()
