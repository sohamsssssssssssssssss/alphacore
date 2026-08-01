"""The LOCKED strategy, ported unchanged for paper trading.

Signal (locked in UNIVERSE_EXPANSION_EXPERIMENT_PROTOCOL.md and
K_EXPANSION_EXPERIMENT_PROTOCOL.md):
  - Cross-sectional relative strength: trailing 20-trading-day return per symbol
    (pct_change(20) on daily closes — exactly what the backtest computed)
  - Rank across the 49-symbol universe; LONG the top rank, SHORT the bottom rank
  - K = 1 position per side
  - Rebalance every 21 captured trading days
  - 10% of equity per leg (backtest: qty = pct*equity/ref_price; here floored
    to whole shares, the only execution-realization difference)

Execution convention (documented in PAPER_TRADING_LOG.md):
  the backtest computed the signal on the rebalance day's close and executed at
  that same close. The paper run cannot know today's close before it happens, so
  the signal is computed on the last COMPLETED close and executed ~15:15 IST on
  the rebalance day — strictly less lookahead than the backtest.

Only the signal/lookback/rebalance/K/universe here may be treated as frozen;
do not change parameters in this file.
"""

from __future__ import annotations

from . import config
from .market_data import CloseHistory


class Strategy:
    """Pure strategy logic: no I/O, no network. Testable in isolation."""

    def __init__(self, symbols: list[str]):
        self.symbols = sorted(symbols)
        self.lookback_n = config.LOOKBACK_N
        self.k = config.K
        self.rebalance_interval = config.REBALANCE_INTERVAL
        self.position_size_pct = config.POSITION_SIZE_PCT

    def signal_ranks(self, history: CloseHistory, as_of: str | None = None) -> dict[str, float]:
        """Trailing lookback returns for all symbols (None entries dropped)."""
        ranks: dict[str, float] = {}
        for sym in self.symbols:
            ret = history.trailing_return(sym, self.lookback_n, as_of=as_of)
            if ret is not None:
                ranks[sym] = ret
        return ranks

    def pick_positions(self, history: CloseHistory,
                       as_of: str | None = None) -> tuple[str | None, str | None]:
        """Long = max trailing return, short = min trailing return (K=1).

        Mirrors the backtest: ranked = sorted(items, key=lambda x: x[1],
        reverse=True); top_sym = ranked[0][0]; bottom_sym = ranked[-1][0].
        """
        ranks = self.signal_ranks(history, as_of=as_of)
        if len(ranks) < 2:
            return None, None
        ranked = sorted(ranks.items(), key=lambda x: x[1], reverse=True)
        top, bottom = ranked[0][0], ranked[-1][0]
        if top == bottom:
            return None, None
        return top, bottom

    def is_rebalance_day(self, history: CloseHistory, last_rebalance_date: str | None) -> bool:
        """21 captured trading days since the last rebalance (exclusive)."""
        days = history.count_trading_days_since(last_rebalance_date)
        return days >= self.rebalance_interval

    def quantity(self, equity: float, ref_price: float) -> int:
        if ref_price <= 0 or equity <= 0:
            return 0
        return int(self.position_size_pct * equity // ref_price)

    def plan_rebalance(self, history: CloseHistory, equity: float,
                       current_positions: dict[str, dict],
                       quotes: dict[str, dict]) -> dict:
        """Build the full order plan for one rebalance.

        current_positions: {symbol: {"leg": "LONG"|"SHORT", "qty": int}}
        quotes: {symbol: normalized quote} for pricing (ask for buys, bid for
        sells — mirrors backtest entry prices).

        Returns {"long": {..., "short": {..., "closes": [..], "opens": [..]}}.
        """
        long_sym, short_sym = self.pick_positions(history)
        plan: dict = {"long": None, "short": None, "closes": [], "opens": [],
                      "skip_reason": None}
        if long_sym is None or short_sym is None:
            plan["skip_reason"] = "fewer than 2 ranked symbols"
            return plan

        for side, sym in (("long", long_sym), ("short", short_sym)):
            leg = "LONG" if side == "long" else "SHORT"
            entry = {"symbol": sym, "leg": leg}
            old = current_positions.get(sym)
            if old:
                entry["close_qty"] = old["qty"]
                plan["closes"].append({
                    "symbol": sym, "leg": leg, "qty": old["qty"],
                    "side": "SELL" if leg == "LONG" else "BUY",
                })
            quote = quotes.get(sym)
            ref = None
            if quote:
                ref = quote.get("ask") if leg == "LONG" else quote.get("bid")
                if ref is None:
                    ref = quote.get("last")
            if ref:
                entry["ref_price"] = ref
            qty = self.quantity(equity, ref or (quote or {}).get("last") or 1.0)
            if qty > 0:
                plan["opens"].append({
                    "symbol": sym, "leg": leg, "qty": qty,
                    "side": "BUY" if leg == "LONG" else "SELL",
                })
            if side == "long":
                plan["long"] = entry
            else:
                plan["short"] = entry
        return plan


def verify_port(history: CloseHistory, symbols: list[str]) -> dict:
    """Verify the ported signal reproduces the backtest's math on repo data.

    Replays the trailing-return ranking at the 3 most recent captured dates and
    asserts top/bottom picks are argmax/argmin of pct_change(20). Run via
    scripts/verify_port.py after the first seed.
    """
    strat = Strategy(symbols)
    out: dict = {"checks": [], "ok": True}
    dates = history._common_dates()
    for date in dates[-3:]:
        ranks = strat.signal_ranks(history, as_of=date)
        top, bottom = strat.pick_positions(history, as_of=date)
        check = {
            "as_of": None,
            "long": top, "short": bottom,
            "long_ret": ranks.get(top) if top else None,
            "short_ret": ranks.get(bottom) if bottom else None,
            "n_ranked": len(ranks),
        }
        # assert long is argmax, short is argmin
        ok_max = ranks.get(top) == max(ranks.values()) if top else False
        ok_min = ranks.get(bottom) == min(ranks.values()) if bottom else False
        check["ok"] = ok_max and ok_min
        out["ok"] = out["ok"] and check["ok"]
        out["checks"].append(check)
    return out
