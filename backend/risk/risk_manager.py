from __future__ import annotations

from collections import deque
from datetime import datetime, timezone


class RiskViolationException(Exception):
    def __init__(self, rule: str, value: float, limit: float):
        self.rule = str(rule)
        self.value = float(value)
        self.limit = float(limit)
        super().__init__(f"Risk violation: {self.rule} = {self.value:.2f} exceeds limit {self.limit:.2f}")


class RiskGate:
    def __init__(
        self,
        max_position_inr: float = 500000.0,
        max_daily_loss: float = 50000.0,
        max_drawdown_pct: float = 0.05,
        max_order_rate_per_min: int = 60,
        max_concentration_pct: float = 0.50,
        starting_capital: float = 100000.0,
        max_price_drop_pct: float = 0.03,
        price_drop_window_seconds: float = 120.0,
        max_price_rise_pct: float = 0.03,
    ):
        self.max_position_inr = float(max_position_inr)
        self.max_daily_loss = float(max_daily_loss)
        self.max_drawdown_pct = float(max_drawdown_pct)
        self.max_order_rate_per_min = int(max_order_rate_per_min)
        self.max_concentration_pct = float(max_concentration_pct)
        self.starting_capital = float(starting_capital)
        self.max_price_drop_pct = float(max_price_drop_pct)
        self.price_drop_window_seconds = float(price_drop_window_seconds)
        self.max_price_rise_pct = float(max_price_rise_pct)
        self._price_history: dict[str, deque] = {}
        self._halted_symbols: set[str] = set()

        self._order_timestamps: deque[datetime] = deque()
        self._is_halted = False
        self._last_daily_pnl = 0.0
        self._last_drawdown_pct = 0.0
        self._total_orders: int = 0
        self._total_fills: int = 0

    def _prune_orders(self) -> None:
        now = datetime.now(timezone.utc)
        cutoff = now.timestamp() - 60.0
        while self._order_timestamps and self._order_timestamps[0].timestamp() < cutoff:
            self._order_timestamps.popleft()

    def evaluate_order(
        self,
        symbol: str,
        side: str,
        qty: int,
        price: float,
        current_positions: dict,
        current_pnl: float,
        peak_pnl: float,
    ) -> bool:
        _ = side
        _ = current_positions

        self._last_daily_pnl = float(current_pnl)

        # 1) Max position value check.
        order_value = float(qty) * float(price)
        if order_value > self.max_position_inr:
            self._is_halted = True
            raise RiskViolationException("max_position_inr", order_value, self.max_position_inr)

        # 2) Daily loss check.
        if float(current_pnl) < -self.max_daily_loss:
            self._is_halted = True
            raise RiskViolationException("daily_loss", abs(float(current_pnl)), self.max_daily_loss)

        # 3) Drawdown halt check.
        if self.check_drawdown_halt(current_pnl=float(current_pnl), peak_pnl=float(peak_pnl)):
            self._is_halted = True
            raise RiskViolationException("drawdown_pct", self._last_drawdown_pct, self.max_drawdown_pct)

        # 4) Order-rate check (> max in trailing 60s).
        self._prune_orders()
        if len(self._order_timestamps) >= self.max_order_rate_per_min:
            self._is_halted = True
            raise RiskViolationException("order_rate_per_min", float(len(self._order_timestamps) + 1), float(self.max_order_rate_per_min))

        # 5) Concentration check.
        concentration = order_value / self.starting_capital if self.starting_capital > 0 else 0.0
        if concentration > self.max_concentration_pct:
            self._is_halted = True
            raise RiskViolationException("concentration_pct", concentration, self.max_concentration_pct)

        # 6) Price dump detection.
        if symbol in self._halted_symbols:
            raise RiskViolationException("price_dump_halt", 0.0, 0.0)

        # 7) Price pump detection.
        if symbol in self._halted_symbols:
            raise RiskViolationException("price_pump_halt", 0.0, 0.0)

        self.record_order()
        self._is_halted = False
        return True

    def check_drawdown_halt(self, current_pnl: float, peak_pnl: float) -> bool:
        drawdown = (float(peak_pnl) - float(current_pnl)) / self.starting_capital if self.starting_capital > 0 else 0.0
        self._last_drawdown_pct = float(drawdown)
        return bool(drawdown >= self.max_drawdown_pct)

    def record_order(self) -> None:
        now = datetime.now(timezone.utc)
        self._order_timestamps.append(now)
        self._total_orders += 1
        self._prune_orders()

    def record_fill(self) -> None:
        self._total_fills += 1

    def record_price(self, symbol: str, price: float) -> None:
        now = datetime.now(timezone.utc)
        if symbol not in self._price_history:
            self._price_history[symbol] = deque()
        self._price_history[symbol].append((now.timestamp(), float(price)))
        cutoff = now.timestamp() - self.price_drop_window_seconds
        while self._price_history[symbol] and self._price_history[symbol][0][0] < cutoff:
            self._price_history[symbol].popleft()

    def check_price_dump(self, symbol: str, current_price: float) -> bool:
        if symbol not in self._price_history or len(self._price_history[symbol]) < 1:
            return False
        oldest_price = self._price_history[symbol][0][1]
        if oldest_price <= 0:
            return False
        drop_pct = (oldest_price - current_price) / oldest_price
        if drop_pct >= self.max_price_drop_pct:
            self._halted_symbols.add(symbol)
            return True
        return False

    def check_price_pump(self, symbol: str, current_price: float) -> bool:
        if symbol not in self._price_history or len(self._price_history[symbol]) < 1:
            return False
        oldest_price = self._price_history[symbol][0][1]
        if oldest_price <= 0:
            return False
        rise_pct = (current_price - oldest_price) / oldest_price
        if rise_pct >= self.max_price_rise_pct:
            self._halted_symbols.add(symbol)
            return True
        return False

    def get_status(self) -> dict:
        self._prune_orders()
        otr = (self._total_orders / self._total_fills) if self._total_fills > 0 else 0.0
        return {
            "is_halted": bool(self._is_halted),
            "daily_pnl": float(self._last_daily_pnl),
            "drawdown_pct": float(self._last_drawdown_pct),
            "orders_last_min": int(len(self._order_timestamps)),
            "halted_symbols": list(self._halted_symbols),
            "total_orders": self._total_orders,
            "total_fills": self._total_fills,
            "otr": float(otr),
        }
