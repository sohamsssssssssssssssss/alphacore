"""Order-to-Trade Ratio monitor for symbols."""

from __future__ import annotations

from datetime import datetime


class OTRMonitor:
    def __init__(self, threshold: float = 10.0):
        self.threshold = threshold
        self._counts: dict[str, dict] = {}

    def record_order(self, symbol: str):
        self._ensure(symbol)
        self._counts[symbol.upper()]["orders"] += 1

    def record_trade(self, symbol: str):
        self._ensure(symbol)
        self._counts[symbol.upper()]["trades"] += 1

    def get_otr(self, symbol: str) -> float:
        d = self._counts.get(symbol.upper(), {})
        trades = d.get("trades", 0)
        orders = d.get("orders", 0)
        return orders / trades if trades > 0 else float(orders)

    def is_breached(self, symbol: str) -> bool:
        return self.get_otr(symbol) > self.threshold

    def summary(self) -> dict:
        return {
            sym: {
                "otr": self.get_otr(sym),
                "orders": v["orders"],
                "trades": v["trades"],
                "breached": self.is_breached(sym),
            }
            for sym, v in self._counts.items()
        }

    def _ensure(self, symbol: str):
        normalized_symbol = symbol.upper()
        if normalized_symbol not in self._counts:
            self._counts[normalized_symbol] = {
                "orders": 0,
                "trades": 0,
                "window_start": datetime.utcnow().isoformat(),
            }


otr_monitor = OTRMonitor()
