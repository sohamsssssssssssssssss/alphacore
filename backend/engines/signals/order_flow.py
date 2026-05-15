from __future__ import annotations

from collections import defaultdict


class OrderFlowSignal:
    def __init__(self):
        self._books: dict[str, dict] = defaultdict(dict)

    def update(self, symbol: str, bids: list[tuple], asks: list[tuple]):
        self._books[symbol.upper()] = {"bids": bids[:5], "asks": asks[:5]}

    def compute(self, symbol: str) -> dict | None:
        book = self._books.get(symbol.upper())
        if not book:
            return None
        bids = book.get("bids", [])
        asks = book.get("asks", [])
        if not bids and not asks:
            return None
        bid_volume = sum(float(q) for _p, q in bids)
        ask_volume = sum(float(q) for _p, q in asks)
        denom = bid_volume + ask_volume
        ofi = ((bid_volume - ask_volume) / denom) if denom > 0 else 0.0

        bid_value = sum(float(p) * float(q) for p, q in bids)
        ask_value = sum(float(p) * float(q) for p, q in asks)
        total_value = bid_value + ask_value
        bid_pressure = (bid_value / total_value) if total_value > 0 else 0.0
        ask_pressure = (ask_value / total_value) if total_value > 0 else 0.0

        direction = "FLAT"
        if ofi > 0.2:
            direction = "LONG"
        elif ofi < -0.2:
            direction = "SHORT"
        strength = abs(ofi)
        return {
            "ofi": float(ofi),
            "signal": float(ofi * 100.0),
            "direction": direction,
            "strength": float(strength),
            "bid_pressure": float(bid_pressure),
            "ask_pressure": float(ask_pressure),
        }
