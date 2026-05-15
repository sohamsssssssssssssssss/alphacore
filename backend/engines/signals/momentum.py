from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone


class MomentumSignal:
    def __init__(self):
        self._prices: dict[str, deque[tuple[datetime, float]]] = defaultdict(lambda: deque(maxlen=100))

    def update(self, symbol: str, price: float, ts: datetime | None):
        if price <= 0:
            return
        now = ts or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        self._prices[symbol.upper()].append((now, float(price)))

    def _price_ago(self, samples: deque[tuple[datetime, float]], now: datetime, seconds: int) -> float | None:
        cutoff = now - timedelta(seconds=seconds)
        candidate = None
        for t, p in reversed(samples):
            if t <= cutoff:
                candidate = p
                break
        return candidate

    def compute(self, symbol: str) -> dict | None:
        samples = self._prices.get(symbol.upper())
        if not samples:
            return None
        now, p_now = samples[-1]
        p_1 = self._price_ago(samples, now, 60)
        p_5 = self._price_ago(samples, now, 300)
        p_15 = self._price_ago(samples, now, 900)
        if p_1 is None or p_5 is None or p_15 is None:
            return None

        mom_1 = ((p_now - p_1) / p_1) * 10000.0 if p_1 else 0.0
        mom_5 = ((p_now - p_5) / p_5) * 10000.0 if p_5 else 0.0
        mom_15 = ((p_now - p_15) / p_15) * 10000.0 if p_15 else 0.0
        signal = 0.2 * mom_1 + 0.5 * mom_5 + 0.3 * mom_15
        direction = "FLAT"
        if signal > 2:
            direction = "LONG"
        elif signal < -2:
            direction = "SHORT"
        strength = min(abs(signal), 100.0) / 100.0
        return {
            "signal": float(signal),
            "direction": direction,
            "strength": float(strength),
            "mom_1min": float(mom_1),
            "mom_5min": float(mom_5),
            "mom_15min": float(mom_15),
        }
