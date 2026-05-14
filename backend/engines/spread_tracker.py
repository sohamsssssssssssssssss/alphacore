"""Bid-ask spread tracker with rolling history."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone


class SpreadTracker:
    def __init__(self, max_history: int = 500):
        self.max_history = max_history
        self._latest: dict[str, dict[str, float]] = {}
        self._history: dict[str, deque[dict]] = defaultdict(lambda: deque(maxlen=max_history))

    def update(self, symbol: str, best_bid: float, best_ask: float) -> None:
        if best_bid <= 0 or best_ask <= 0:
            return
        mid = (best_bid + best_ask) / 2.0
        if mid <= 0:
            return
        spread_abs = best_ask - best_bid
        spread_bps = (spread_abs / mid) * 10000.0
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "bid": float(best_bid),
            "ask": float(best_ask),
            "absolute": float(spread_abs),
            "relative": float(spread_bps),
            "mid": float(mid),
        }
        key = symbol.upper()
        self._latest[key] = row
        self._history[key].append(row)

    def get_spread(self, symbol: str) -> dict:
        return self._latest.get(symbol.upper(), {"absolute": 0.0, "relative": 0.0, "mid": 0.0, "bid": 0.0, "ask": 0.0})

    def get_spread_history(self, symbol: str, n: int = 60) -> list[dict]:
        rows = list(self._history.get(symbol.upper(), deque()))
        return rows[-n:]

    def get_avg_spread(self, symbol: str, window: int = 60) -> float:
        history = self.get_spread_history(symbol, n=window)
        if not history:
            return 0.0
        return sum(row["relative"] for row in history) / len(history)
