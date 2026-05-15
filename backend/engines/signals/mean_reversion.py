from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone
import math

import numpy as np


class MeanReversionSignal:
    def __init__(self):
        self._prices: dict[str, deque[tuple[datetime, float]]] = defaultdict(lambda: deque(maxlen=100))

    def update(self, symbol: str, price: float, ts: datetime | None):
        if price <= 0:
            return
        now = ts or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        self._prices[symbol.upper()].append((now, float(price)))

    def compute(self, symbol: str) -> dict | None:
        samples = self._prices.get(symbol.upper())
        if not samples or len(samples) < 20:
            return None
        arr = np.array([p for _t, p in list(samples)[-20:]], dtype=float)
        cur = float(arr[-1])
        mean = float(arr.mean())
        std = float(arr.std())
        if std == 0:
            z = 0.0
        else:
            z = (cur - mean) / std
        signal = -z
        direction = "FLAT"
        if z < -1.5:
            direction = "LONG"
        elif z > 1.5:
            direction = "SHORT"
        strength = min(abs(z) / 3.0, 1.0)

        lagged = arr[:-1]
        current = arr[1:]
        autocorr = float(np.corrcoef(lagged, current)[0, 1]) if np.std(lagged) > 0 and np.std(current) > 0 else 0.0
        half_life = None
        if 0 < autocorr < 1:
            half_life = math.log(0.5) / math.log(autocorr)

        return {
            "signal": float(signal),
            "direction": direction,
            "strength": float(strength),
            "z_score": float(z),
            "half_life": float(half_life) if half_life is not None else None,
        }
