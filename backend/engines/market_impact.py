"""Simplified market-impact model for execution planning."""

from __future__ import annotations

ADV_BY_SYMBOL = {
    "RELIANCE": 5_000_000,
    "TCS": 2_000_000,
    "INFY": 3_000_000,
    "HDFCBANK": 4_000_000,
    "ICICIBANK": 3_500_000,
}


class MarketImpactModel:
    ETA = 0.1
    GAMMA = 0.05

    def temporary_impact(self, qty: float, adv: float, spread_bps: float) -> float:
        if adv <= 0:
            return float(spread_bps) / 2.0
        participation = max(float(qty), 0.0) / float(adv)
        return float(spread_bps) / 2.0 + self.ETA * (participation ** 0.6)

    def permanent_impact(self, qty: float, adv: float) -> float:
        if adv <= 0:
            return 0.0
        participation = max(float(qty), 0.0) / float(adv)
        return self.GAMMA * participation

    def total_impact(self, qty: float, adv: float, spread_bps: float, reference_price: float = 2500.0) -> dict:
        temporary_bps = self.temporary_impact(qty, adv, spread_bps)
        permanent_bps = self.permanent_impact(qty, adv)
        total_bps = temporary_bps + permanent_bps
        cost_rupees = (total_bps / 10000.0) * float(reference_price) * float(max(qty, 0.0))
        return {
            "temporary_bps": float(temporary_bps),
            "permanent_bps": float(permanent_bps),
            "total_bps": float(total_bps),
            "cost_rupees": float(cost_rupees),
        }

    def price_impact_curve(self, adv: float, spread_bps: float, max_qty_pct: float = 0.10) -> list[dict]:
        effective_adv = float(adv) if adv > 0 else 1.0
        points: list[dict] = []
        for i in range(20):
            qty_pct = (max_qty_pct * i) / 19.0 if i > 0 else 0.0
            qty = qty_pct * effective_adv
            temp = self.temporary_impact(qty, effective_adv, spread_bps)
            perm = self.permanent_impact(qty, effective_adv)
            points.append(
                {
                    "qty_pct": float(qty_pct),
                    "temporary_bps": float(temp),
                    "permanent_bps": float(perm),
                    "total_bps": float(temp + perm),
                }
            )
        return points


market_impact_model = MarketImpactModel()
