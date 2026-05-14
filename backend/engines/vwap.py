"""Rolling VWAP engine for market microstructure analytics."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone


class VWAPEngine:
    def __init__(self, window_config: dict[str, int] | None = None):
        self.window_config = window_config or {
            "1min": 60,
            "5min": 300,
            "15min": 900,
            "session": 6 * 60 * 60,
        }
        self._windows: dict[str, dict[str, deque[tuple[datetime, float, float]]]] = defaultdict(
            lambda: {
                name: deque(maxlen=max(1, seconds * 4))
                for name, seconds in self.window_config.items()
            }
        )
        self._lock = asyncio.Lock()

    async def update(self, symbol: str, price: float, volume: float, ts: datetime | None = None) -> None:
        if price <= 0 or volume <= 0:
            return
        now = ts or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        normalized_symbol = symbol.upper()
        async with self._lock:
            for window_name, window in self._windows[normalized_symbol].items():
                window.append((now, float(price), float(volume)))
                self._prune(window_name, window, now)

    def _prune(self, window_name: str, window: deque[tuple[datetime, float, float]], now: datetime) -> None:
        max_age_seconds = self.window_config[window_name]
        cutoff = now - timedelta(seconds=max_age_seconds)
        while window and window[0][0] < cutoff:
            window.popleft()

    def get_vwap(self, symbol: str, window: str = "5min") -> float | None:
        normalized_symbol = symbol.upper()
        bucket = self._windows.get(normalized_symbol)
        if not bucket or window not in bucket:
            return None
        samples = list(bucket[window])
        if not samples:
            return None
        total_notional = sum(price * volume for _ts, price, volume in samples)
        total_volume = sum(volume for _ts, _price, volume in samples)
        if total_volume <= 0:
            return None
        return total_notional / total_volume

    def get_all(self, symbol: str) -> dict[str, float | None]:
        normalized_symbol = symbol.upper()
        return {name: self.get_vwap(normalized_symbol, name) for name in self.window_config}

    def get_vwap_deviation(self, symbol: str, current_price: float) -> float:
        vwap_5 = self.get_vwap(symbol, "5min")
        if vwap_5 is None or vwap_5 == 0:
            return 0.0
        return ((float(current_price) - vwap_5) / vwap_5) * 10000.0
