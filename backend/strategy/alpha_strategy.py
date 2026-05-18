from __future__ import annotations

import logging
from collections import defaultdict

from strategy.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)


class AlphaStrategy(BaseStrategy):
    def __init__(self, confidence_threshold: float = 0.8, base_qty: int = 10):
        super().__init__()
        self.confidence_threshold = float(confidence_threshold)
        self.base_qty = int(base_qty)
        self._default_base_qty = int(base_qty)
        self.current_regime = 0
        self.positions = defaultdict(int)
        self._mid_prices: dict[str, float] = {}

    def on_orderbook(self, symbol: str, bids: list, asks: list) -> None:
        if not bids or not asks:
            return
        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        self._mid_prices[symbol] = (best_bid + best_ask) / 2.0

    def on_signal(self, symbol: str, model_name: str, prediction: float, confidence: float) -> None:
        _ = model_name
        if float(confidence) <= self.confidence_threshold:
            return

        mid = self._mid_prices.get(symbol)
        if mid is None:
            return

        if float(prediction) > 0.5:
            self.emit_order(symbol, "BUY", self.base_qty, "LIMIT", mid)
        elif float(prediction) < 0.5:
            self.emit_order(symbol, "SELL", self.base_qty, "LIMIT", mid)

    def on_fill(self, symbol: str, qty: int, price: float, side: str) -> None:
        _ = price
        signed_qty = int(qty) if side.upper() == "BUY" else -int(qty)
        self.positions[symbol] += signed_qty

    def on_regime_change(self, old_regime: int, new_regime: int) -> None:
        self.current_regime = int(new_regime)
        if int(new_regime) == 3:
            self.base_qty = max(1, self.base_qty // 2)
        elif int(old_regime) == 3 and int(new_regime) != 3:
            self.base_qty = self._default_base_qty
        logger.info("Regime changed from %s to %s; base_qty=%s", old_regime, new_regime, self.base_qty)
