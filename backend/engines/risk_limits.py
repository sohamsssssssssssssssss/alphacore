"""Pre-trade risk limits for generated signals."""

from __future__ import annotations

from datetime import datetime, timedelta

MAX_POSITION_SIZE = 100_000
MAX_SIGNALS_PER_SYMBOL_PER_HOUR = 10


class RiskLimits:
    def __init__(self):
        self._signal_counts: dict[str, list] = {}

    def check_signal(self, symbol: str, entry_price: float, quantity: int = 100) -> tuple[bool, str]:
        """Returns (allowed, reason). Blocks signal if limits breached."""
        notional = entry_price * quantity
        if notional > MAX_POSITION_SIZE:
            return False, f"Notional {notional:.0f} exceeds max {MAX_POSITION_SIZE}"

        now = datetime.utcnow()
        hour_ago = now - timedelta(hours=1)
        normalized_symbol = symbol.upper()
        counts = self._signal_counts.get(normalized_symbol, [])
        recent = [t for t in counts if t > hour_ago]
        if len(recent) >= MAX_SIGNALS_PER_SYMBOL_PER_HOUR:
            return False, f"Signal rate limit: {len(recent)} signals in last hour"

        recent.append(now)
        self._signal_counts[normalized_symbol] = recent
        return True, "ok"

    def status(self) -> dict:
        return {
            "limits": {
                "max_position_size": MAX_POSITION_SIZE,
                "max_signals_per_symbol_per_hour": MAX_SIGNALS_PER_SYMBOL_PER_HOUR,
            },
            "signal_counts": {
                symbol: [ts.isoformat() for ts in timestamps]
                for symbol, timestamps in self._signal_counts.items()
            },
        }


risk_limits = RiskLimits()
