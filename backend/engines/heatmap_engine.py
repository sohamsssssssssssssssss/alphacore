"""Liquidity heatmap engine for NSE order book data.

Builds a rolling matrix of price level, time, and resting volume so the
frontend can visualize concentrated liquidity and voids over time.
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from models.schemas import HeatmapCell, HeatmapResponse, OrderBookSnapshot


class HeatmapEngine:
    """Capture rolling order-book depth snapshots for heatmap visualization.

    Each tick contributes one cell per visible price level. Over time the cells
    form a price-by-time liquidity matrix that highlights persistent support,
    resistance, and gaps in displayed depth.
    """

    MAX_CELLS_PER_SYMBOL: int = 500
    PRICE_LEVELS_RADIUS: int = 10

    def __init__(self) -> None:
        """Initialize rolling heatmap storage."""

        self._matrices: dict[str, deque[HeatmapCell]] = defaultdict(
            lambda: deque(maxlen=self.MAX_CELLS_PER_SYMBOL)
        )

    def update(self, symbol: str, snapshot: OrderBookSnapshot) -> None:
        """Add the latest order-book levels to the rolling heatmap matrix."""

        normalized_symbol = symbol.upper()
        timestamp = snapshot.timestamp
        bid_map = {level.price: level.volume for level in snapshot.bids[: self.PRICE_LEVELS_RADIUS]}
        ask_map = {level.price: level.volume for level in snapshot.asks[: self.PRICE_LEVELS_RADIUS]}
        price_levels = sorted(set(bid_map) | set(ask_map))

        for price_level in price_levels:
            bid_volume = float(bid_map.get(price_level, 0.0))
            ask_volume = float(ask_map.get(price_level, 0.0))
            self._matrices[normalized_symbol].append(
                HeatmapCell(
                    price_level=float(price_level),
                    bid_volume=round(bid_volume, 2),
                    ask_volume=round(ask_volume, 2),
                    total_volume=round(bid_volume + ask_volume, 2),
                    timestamp=timestamp,
                )
            )

    def get_heatmap(self, symbol: str, window_minutes: int = 30) -> HeatmapResponse:
        """Return heatmap cells for a symbol within the requested time window."""

        normalized_symbol = symbol.upper()
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(minutes=window_minutes)
        cells = [cell for cell in self._matrices.get(normalized_symbol, deque()) if cell.timestamp >= cutoff]
        price_levels = [cell.price_level for cell in cells]
        return HeatmapResponse(
            symbol=normalized_symbol,
            generated_at=now,
            cells=cells,
            price_min=min(price_levels) if price_levels else 0.0,
            price_max=max(price_levels) if price_levels else 0.0,
            time_window_minutes=window_minutes,
        )

    def get_latest_cells(self, symbol: str, timestamp: datetime) -> list[HeatmapCell]:
        """Return cells captured for a symbol at a specific snapshot timestamp."""

        return [
            cell
            for cell in self._matrices.get(symbol.upper(), deque())
            if cell.timestamp == timestamp
        ]


heatmap_engine = HeatmapEngine()
