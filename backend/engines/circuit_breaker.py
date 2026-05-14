"""Circuit breaker guard for per-symbol extreme price moves."""

from __future__ import annotations

from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class CircuitBreaker:
    def __init__(self):
        self.halted: dict[str, dict] = {}

    def check(self, symbol: str, current_price: float, prev_price: float) -> bool:
        """Returns True if trading should be halted for this symbol."""
        normalized_symbol = symbol.upper()
        if normalized_symbol in self.halted:
            return True

        pct_change = abs((current_price - prev_price) / prev_price) if prev_price else 0
        if pct_change > 0.05:
            self.halted[normalized_symbol] = {
                "reason": f"Price moved {pct_change:.2%} in one cycle",
                "halted_at": datetime.utcnow().isoformat(),
                "price_at_halt": current_price,
            }
            logger.warning("CIRCUIT BREAKER: %s halted — %.2f%% move", normalized_symbol, pct_change * 100)
            return True
        return False

    def reset(self, symbol: str):
        self.halted.pop(symbol.upper(), None)

    def status(self) -> dict:
        return self.halted


circuit_breaker = CircuitBreaker()
