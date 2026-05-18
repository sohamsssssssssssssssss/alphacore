from __future__ import annotations

from abc import ABC, abstractmethod


class BaseStrategy(ABC):
    def __init__(self) -> None:
        self._order_queue: list[dict] = []

    @abstractmethod
    def on_orderbook(self, symbol: str, bids: list, asks: list) -> None:
        pass

    @abstractmethod
    def on_signal(self, symbol: str, model_name: str, prediction: float, confidence: float) -> None:
        pass

    @abstractmethod
    def on_fill(self, symbol: str, qty: int, price: float, side: str) -> None:
        pass

    @abstractmethod
    def on_regime_change(self, old_regime: int, new_regime: int) -> None:
        pass

    def emit_order(self, symbol, side, qty, order_type, price=None) -> None:
        self._order_queue.append(
            {
                "symbol": symbol,
                "side": side,
                "qty": int(qty),
                "order_type": order_type,
                "price": price,
            }
        )

    def get_pending_orders(self) -> list:
        out = list(self._order_queue)
        self._order_queue.clear()
        return out
