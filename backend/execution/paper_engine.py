from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from uuid import uuid4


class PaperTradingEngine:
    def __init__(self, starting_capital: float = 100000.0):
        self.positions = defaultdict(int)
        self.cash = float(starting_capital)
        self.starting_capital = float(starting_capital)
        self.peak_capital = float(starting_capital)
        self.pnl = 0.0
        self.daily_pnl = 0.0
        self.trades: list[dict] = []
        self.pending_orders: list[dict] = []
        self.last_prices: dict[str, float] = {}
        self._current_day = date.today()

    def submit_order(self, symbol: str, side: str, qty: int, order_type: str, price: float = None) -> str:
        normalized_side = side.upper()
        normalized_type = order_type.upper()
        if qty <= 0:
            raise ValueError("qty must be > 0")
        if normalized_side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL")
        if normalized_type not in {"MARKET", "LIMIT"}:
            raise ValueError("order_type must be MARKET or LIMIT")
        if normalized_type == "LIMIT" and price is None:
            raise ValueError("LIMIT order requires price")

        order_id = str(uuid4())
        self.pending_orders.append(
            {
                "order_id": order_id,
                "symbol": symbol,
                "side": normalized_side,
                "qty": int(qty),
                "order_type": normalized_type,
                "price": float(price) if price is not None else None,
                "submitted_at": datetime.now(timezone.utc),
            }
        )
        return order_id

    def _mark_to_market_capital(self) -> float:
        exposure = 0.0
        for sym, qty in self.positions.items():
            px = float(self.last_prices.get(sym, 0.0))
            exposure += float(qty) * px
        return float(self.cash + exposure)

    def _update_pnl(self) -> None:
        current_capital = self._mark_to_market_capital()
        self.pnl = float(current_capital - self.starting_capital)
        self.daily_pnl = float(current_capital - self.starting_capital)
        if current_capital > self.peak_capital:
            self.peak_capital = float(current_capital)

    def process_market_tick(self, symbol: str, best_bid: float, best_ask: float) -> list:
        fills: list[dict] = []
        mid = (float(best_bid) + float(best_ask)) / 2.0
        self.last_prices[symbol] = mid

        remaining: list[dict] = []
        for order in self.pending_orders:
            if order["symbol"] != symbol:
                remaining.append(order)
                continue

            should_fill = False
            fill_price = None
            if order["order_type"] == "MARKET":
                should_fill = True
                fill_price = float(best_ask) if order["side"] == "BUY" else float(best_bid)
            elif order["order_type"] == "LIMIT":
                if order["side"] == "BUY" and float(best_ask) <= float(order["price"]):
                    should_fill = True
                    fill_price = float(order["price"])
                elif order["side"] == "SELL" and float(best_bid) >= float(order["price"]):
                    should_fill = True
                    fill_price = float(order["price"])

            if not should_fill:
                remaining.append(order)
                continue

            qty = int(order["qty"])
            notional = float(fill_price) * qty
            signed_qty = qty if order["side"] == "BUY" else -qty

            self.positions[symbol] += signed_qty
            if order["side"] == "BUY":
                self.cash -= notional
            else:
                self.cash += notional

            fill = {
                "order_id": order["order_id"],
                "symbol": symbol,
                "side": order["side"],
                "qty": qty,
                "price": float(fill_price),
                "notional": notional,
                "filled_at": datetime.now(timezone.utc),
            }
            self.trades.append(fill)
            fills.append(fill)

        self.pending_orders = remaining
        self._update_pnl()
        return fills

    def get_realtime_metrics(self) -> dict:
        current_capital = self._mark_to_market_capital()
        peak_pnl = float(self.peak_capital - self.starting_capital)
        max_drawdown = 0.0
        if self.peak_capital > 0:
            max_drawdown = float((self.peak_capital - current_capital) / self.peak_capital)

        capital_usage = 0.0
        for sym, qty in self.positions.items():
            last_px = float(self.last_prices.get(sym, 0.0))
            capital_usage += abs(float(qty) * last_px)
        capital_usage = float(capital_usage / self.starting_capital) if self.starting_capital > 0 else 0.0

        return {
            "pnl": float(self.pnl),
            "daily_pnl": float(self.daily_pnl),
            "peak_pnl": peak_pnl,
            "max_drawdown": max_drawdown,
            "capital_usage": capital_usage,
            "open_positions": dict(self.positions),
            "total_trades": len(self.trades),
        }

    def reset_daily_pnl(self) -> None:
        self.daily_pnl = 0.0
        self._current_day = date.today()
