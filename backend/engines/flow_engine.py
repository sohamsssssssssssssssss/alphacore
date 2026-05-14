"""Order flow imbalance calculator for NSE order book data.

Tracks aggressive buying vs aggressive selling pressure in real time by
comparing consecutive snapshots and estimating when liquidity was hit at
unchanged top-of-book prices.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from datetime import datetime, timezone

from models.schemas import FlowImbalance, OrderBookSnapshot

logger = logging.getLogger(__name__)


class FlowEngine:
    """Estimate order flow dominance from evolving top-of-book liquidity.

    The engine infers aggression from quote depletion. If ask volume drops at
    the same price, buyers likely crossed the spread and lifted offers. If bid
    volume drops at the same price, sellers likely hit bids. Rolling buy and
    sell deques provide short-horizon imbalance scores.
    """

    WINDOW_1MIN: int = 2
    WINDOW_5MIN: int = 10
    MAX_HISTORY: int = 50

    def __init__(self) -> None:
        """Initialize rolling state for all tracked symbols."""

        self._buy_volume: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=self.WINDOW_5MIN)
        )
        self._sell_volume: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=self.WINDOW_5MIN)
        )
        self._prev_snapshots: dict[str, OrderBookSnapshot] = {}
        self._current_flow: dict[str, FlowImbalance] = {}
        self._flow_history: dict[str, deque[FlowImbalance]] = defaultdict(
            lambda: deque(maxlen=self.MAX_HISTORY)
        )
        self._flow_5min: dict[str, FlowImbalance] = {}

    def update(self, symbol: str, snapshot: OrderBookSnapshot) -> FlowImbalance:
        """Update rolling flow estimates and return the current 1-minute score."""

        normalized_symbol = symbol.upper()
        prev = self._prev_snapshots.get(normalized_symbol)
        aggressive_buys = 0.0
        aggressive_sells = 0.0
        if prev is not None:
            aggressive_buys, aggressive_sells = self._detect_aggressive_volume(prev, snapshot)

        self._buy_volume[normalized_symbol].append(aggressive_buys)
        self._sell_volume[normalized_symbol].append(aggressive_sells)

        buys_1m = deque(list(self._buy_volume[normalized_symbol])[-self.WINDOW_1MIN :])
        sells_1m = deque(list(self._sell_volume[normalized_symbol])[-self.WINDOW_1MIN :])
        imbalance_1m = self._calculate_imbalance(buys_1m, sells_1m)

        buys_5m = deque(self._buy_volume[normalized_symbol], maxlen=self.WINDOW_5MIN)
        sells_5m = deque(self._sell_volume[normalized_symbol], maxlen=self.WINDOW_5MIN)
        imbalance_5m = self._calculate_imbalance(buys_5m, sells_5m)

        current = FlowImbalance(
            symbol=normalized_symbol,
            timestamp=snapshot.timestamp,
            imbalance_score=imbalance_1m,
            aggressive_buys=round(sum(buys_1m), 2),
            aggressive_sells=round(sum(sells_1m), 2),
            window_minutes=1,
        )
        self._current_flow[normalized_symbol] = current
        self._flow_history[normalized_symbol].append(current)
        self._flow_5min[normalized_symbol] = FlowImbalance(
            symbol=normalized_symbol,
            timestamp=snapshot.timestamp,
            imbalance_score=imbalance_5m,
            aggressive_buys=round(sum(buys_5m), 2),
            aggressive_sells=round(sum(sells_5m), 2),
            window_minutes=5,
        )
        self._prev_snapshots[normalized_symbol] = snapshot
        return current

    def _detect_aggressive_volume(
        self,
        prev: OrderBookSnapshot,
        curr: OrderBookSnapshot,
    ) -> tuple[float, float]:
        """Detect quote depletion that implies aggressive buying or selling."""

        prev_asks = {level.price: level.volume for level in prev.asks}
        curr_asks = {level.price: level.volume for level in curr.asks}
        prev_bids = {level.price: level.volume for level in prev.bids}
        curr_bids = {level.price: level.volume for level in curr.bids}

        aggressive_buys = 0.0
        aggressive_sells = 0.0

        for price, prev_volume in prev_asks.items():
            curr_volume = curr_asks.get(price)
            if curr_volume is not None and curr_volume < prev_volume:
                aggressive_buys += prev_volume - curr_volume

        for price, prev_volume in prev_bids.items():
            curr_volume = curr_bids.get(price)
            if curr_volume is not None and curr_volume < prev_volume:
                aggressive_sells += prev_volume - curr_volume

        return round(aggressive_buys, 2), round(aggressive_sells, 2)

    def _calculate_imbalance(self, buys: deque[float], sells: deque[float]) -> float:
        """Compute a clamped imbalance score from rolling buy and sell totals."""

        total_buys = float(sum(buys))
        total_sells = float(sum(sells))
        denominator = total_buys + total_sells
        if denominator == 0:
            return 0.0
        imbalance = (total_buys - total_sells) / denominator
        return round(max(-1.0, min(1.0, imbalance)), 4)

    def get_current_flow(self, symbol: str) -> FlowImbalance | None:
        """Return the latest 1-minute flow imbalance for a symbol."""

        return self._current_flow.get(symbol.upper())

    def get_flow_history(self, symbol: str, count: int) -> list[FlowImbalance]:
        """Return the last N 1-minute flow imbalance readings for a symbol."""

        return list(self._flow_history.get(symbol.upper(), deque()))[-count:]

    def get_flow_window(self, symbol: str, window_minutes: int) -> FlowImbalance | None:
        """Return the latest flow reading for a supported rolling window."""

        normalized_symbol = symbol.upper()
        if window_minutes == 1:
            return self._current_flow.get(normalized_symbol)
        if window_minutes == 5:
            return self._flow_5min.get(normalized_symbol)
        return None


flow_engine = FlowEngine()
