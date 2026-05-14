"""Composite liquidity scoring engine."""

from __future__ import annotations

import math

import numpy as np


class LiquidityScorer:
    def __init__(self):
        self._scores: dict[str, dict] = {}

    def update(self, symbol: str, spread_bps: float, depth: float, otr: float, price_history: list[float]) -> None:
        spread_score = 100.0 - min(max(spread_bps, 0.0) / 2.0, 100.0)

        safe_depth = max(float(depth), 0.0)
        depth_score = min(100.0, max(0.0, math.log10(1.0 + safe_depth) / 5.0 * 100.0))

        otr_score = 100.0 - min(max(float(otr), 0.0) * 5.0, 100.0)

        if len(price_history) >= 2 and np.mean(price_history) > 0:
            mean_price = float(np.mean(price_history))
            std_price = float(np.std(price_history))
            price_std_bps = (std_price / mean_price) * 10000.0
        else:
            price_std_bps = 0.0
        volatility_score = 100.0 - min(price_std_bps / 10.0, 100.0)

        total = float((spread_score + depth_score + otr_score + volatility_score) / 4.0)

        grade = "F"
        if total >= 80:
            grade = "A"
        elif total >= 60:
            grade = "B"
        elif total >= 40:
            grade = "C"
        elif total >= 20:
            grade = "D"

        self._scores[symbol.upper()] = {
            "total": total,
            "components": {
                "spread": float(spread_score),
                "depth": float(depth_score),
                "otr": float(otr_score),
                "volatility": float(volatility_score),
            },
            "grade": grade,
        }

    def get_score(self, symbol: str) -> dict:
        return self._scores.get(symbol.upper(), {"total": 0.0, "components": {"spread": 0.0, "depth": 0.0, "otr": 0.0, "volatility": 0.0}, "grade": "F"})

    def get_all_scores(self) -> dict[str, dict]:
        return self._scores
