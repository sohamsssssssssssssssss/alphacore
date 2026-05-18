from __future__ import annotations

import math


class CostModel:
    def __init__(
        self,
        k_impact: float = 0.0015,
        brokerage_per_trade: float = 20.0,
        stt_rate: float = 0.001,
        adv_lookup: dict[str, float] | None = None,
    ):
        self.k_impact = float(k_impact)
        self.brokerage_per_trade = float(brokerage_per_trade)
        self.stt_rate = float(stt_rate)
        self.adv_lookup = adv_lookup or {}

    def market_impact(self, price: float, qty: float, adv: float | None) -> float:
        if qty <= 0 or price <= 0:
            return 0.0
        eff_adv = float(adv) if adv is not None and adv > 0 else float(qty)
        impact = self.k_impact * math.sqrt(float(qty) / eff_adv) * float(price) * float(qty)
        return float(max(0.0, impact))

    def spread_cost(self, spread_bps: float, price: float, qty: float) -> float:
        if qty <= 0 or price <= 0:
            return 0.0
        cost = ((float(spread_bps) / 10000.0) / 2.0) * float(price) * float(qty)
        return float(max(0.0, cost))

    def total_cost(self, price: float, qty: float, adv: float | None, spread_bps: float, side: str) -> float:
        if qty <= 0 or price <= 0:
            return 0.0
        stt = self.stt_rate * float(price) * float(qty) if side.upper() == "SELL" else 0.0
        total = (
            self.market_impact(price, qty, adv)
            + self.spread_cost(spread_bps, price, qty)
            + self.brokerage_per_trade
            + stt
        )
        return float(max(0.0, total))
