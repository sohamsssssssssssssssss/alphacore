"""
AlphaCore Phase 1, Step 1 — top-quartile basket + rebalance-frequency backtest.

Config-level extension of the K=1 cross-sectional relative-strength pipeline.
The SIGNAL is untouched (rs_signal.py: 21-day lookback, cross-sectional
ranking); only the portfolio-construction layer changes:

  * selection:   top-quartile basket (k = n_ranked // 4, i.e. 12 of 49)
                 instead of top-1, delegating ranking to the untouched
                 rs_signal.rank_table
  * rebalance:   monthly (existing schedule) OR quarterly (helper defined here)

Metrics reuse the repo's canonical calculations (nothing reimplemented):

  * Sharpe: engines/backtest_metrics.compute_sharpe on per-rebalance returns,
    annualized by the matching factor (12 for monthly, 4 for quarterly).
  * 95% CI: engines/backtest_metrics.stationary_bootstrap_sharpe_ci
    (Politis-Romano stationary bootstrap, repo defaults).
  * Costs:  engines/cost_model.CostModel defaults (k_impact=0.0015,
    brokerage Rs 20/trade, STT 0.1% sell-side) + the research backtest's
    assumed 10 bps half-spread.
  * Win-alignment: beats-market rate — % of periods where the equal-weighted
    basket's GROSS forward holding-period return exceeds the equal-weighted
    all-universe GROSS forward return over the same window.
  * Turnover: avg trade legs per rebalance + avg one-sided turnover fraction.

Execution convention (from the harness docstring): orders derived from the
as-of ranking are executed AFTER that close — next session's open. Fills and
costs use the next-session open after each rebalance close.

Run from backend/ (python3.11, sandbox/.venv):
    python3.11 -m experiments.basket_backtest --frequency monthly
    python3.11 -m experiments.basket_backtest --frequency quarterly

Phase 2 (overfit sanity check) parameters:
    --k N          override basket size (default: top-quartile n_ranked//4)
    --lookback N   signal lookback in trading sessions (default: 21)
    --start DATE   exclude rebalances before DATE (split-sample runs; prior
                   price history is kept so the first ranking has a lookback)
    --as-of DATE   data cutoff (default: today)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import pickle
import sys
from datetime import date

import pandas as pd

# Sibling sandbox modules (mirrors conftest.py / harness.py).
_SANDBOX_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sandbox")
sys.path.insert(0, os.path.dirname(_SANDBOX_DIR))
if _SANDBOX_DIR not in sys.path:
    sys.path.insert(0, _SANDBOX_DIR)

from prices import fetch_daily_bars
from rs_signal import (LOOKBACK_TRADING_DAYS, last_trading_day_of_month,
                       rank_table, rebalance_dates)
from universe import UNIVERSE_49

try:  # repo canonical metrics/cost functions (required for a real run)
    from engines.backtest_metrics import compute_sharpe, stationary_bootstrap_sharpe_ci
    from engines.cost_model import CostModel

    REPO_ENGINES_AVAILABLE = True
except Exception:  # pragma: no cover - degraded import only
    compute_sharpe = None  # type: ignore
    stationary_bootstrap_sharpe_ci = None  # type: ignore
    CostModel = None  # type: ignore
    REPO_ENGINES_AVAILABLE = False

DEFAULT_BUDGET_INR = 1_000_000.0
ASSUMED_SPREAD_BPS = 10.0  # research backtest's half-spread assumption
FETCH_PERIOD_DAYS = 2190  # ~6y of daily bars, approximating the original backtest window

_QUARTER_END_MONTHS = (3, 6, 9, 12)


# ---------------------------------------------------------------------------
# Selection (portfolio-construction layer only; signal logic untouched)
# ---------------------------------------------------------------------------

def top_quartile(closes: pd.DataFrame, as_of: date, k: int | None = None,
                 lookback: int = LOOKBACK_TRADING_DAYS,
                 eligible: set[str] | None = None) -> list[str]:
    """
    Top-quartile basket: the best-ranked n//4 symbols with data as of `as_of`.

    For the 49-symbol universe this is 49//4 = 12 names (per the brief,
    "~12 out of 49"). Pass `k` explicitly to override the basket size
    (Phase 2 sensitivity). Falls back to at least 1 name. Ranking is
    delegated to rs_signal.rank_table (lookback parameterized for Phase 2).
    `eligible`, when given, restricts ranking to those symbols (None = all).
    """
    ranked = [s for s, row in rank_table(closes, as_of, lookback=lookback).iterrows()
              if bool(row["has_data"]) and (eligible is None or s in eligible)]
    k_eff = max(1, len(ranked) // 4) if k is None else k
    return ranked[:k_eff]


# ---------------------------------------------------------------------------
# Rebalance scheduling
# ---------------------------------------------------------------------------

def quarterly_rebalance_dates(closes: pd.DataFrame, end: date, quarters_back: int = 24) -> list[date]:
    """
    Last trading day of each quarter-end month (Mar/Jun/Sep/Dec) within
    [end - quarters_back*3 months, end], from the closes trading calendar.
    """
    dates: list[date] = []
    y, m = end.year, end.month
    for _ in range(quarters_back * 3 + 1):  # months, not quarters
        if m in _QUARTER_END_MONTHS:
            d = last_trading_day_of_month(closes, y, m)
            if d is not None and d <= end:
                dates.append(d)
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return sorted(dates)


def monthly_rebalance_dates(closes: pd.DataFrame, end: date, months_back: int = 72) -> list[date]:
    """Monthly schedule via the existing rs_signal helper (unchanged logic)."""
    return rebalance_dates(closes, end, months_back=months_back)


def execution_day(closes: pd.DataFrame, rebalance: date) -> date | None:
    """First trading day strictly after `rebalance` (next-session open fills)."""
    later = closes.index[closes.index > pd.Timestamp(rebalance)]
    if len(later) == 0:
        return None
    return later[0].date()


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def _last_price(series: pd.Series, day: date) -> float | None:
    """Last available price on/before `day` for one symbol (fallback for gaps)."""
    rows = series.loc[series.index <= pd.Timestamp(day)]
    if len(rows) == 0:
        return None
    val = float(rows.iloc[-1])
    return val if math.isfinite(val) else None


def simulate(
    closes: pd.DataFrame,
    adv: dict[str, float],
    opens: pd.DataFrame,
    rebalance_dates_list: list[date],
    *,
    budget: float = DEFAULT_BUDGET_INR,
    spread_bps: float = ASSUMED_SPREAD_BPS,
    k: int | None = None,
    lookback: int = LOOKBACK_TRADING_DAYS,
    adv_by_date: dict[date, dict[str, float]] | None = None,
    trace: list | None = None,
) -> dict:
    """
    Run the equal-weighted-at-entry top-quartile basket backtest.

    adv_by_date ({rebalance_date: {sym: adv}}), when given, supplies the ADV
    used for impact costs at each rebalance and replaces the single `adv`
    dict. Only symbols with an entry at a rebalance are rankable there, and a
    traded symbol with no entry raises; nothing is substituted. With None, the
    legacy single-ADV path runs unchanged. In that mode the result also
    carries total_costs.

    Per rebalance: at the NEXT session's open after the rebalance close, trade
    only the DELTA of the basket — sell names leaving the basket, buy names
    entering it — and hold the rest (no top-up rebalancing to exact equal
    weights between rebalances). This is the convention that actually tests
    the diversification hypothesis: only names the signal rotates get traded
    and charged repo-CostModel costs. New buys are sized at budget/k split.

    Period returns are equity-based (equity just after fills at end-of-period /
    equity just after fills at start-of-period - 1) — the per-rebalance
    sampling used by the original 9-config table.

    Note: buys are sized at budget/k notional and costs are paid from cash, so
    cash may run marginally negative at inception (<< 0.1% of budget) — the
    standard convention when costs are not reserved from the sizing.
    """
    if not REPO_ENGINES_AVAILABLE:
        raise RuntimeError("engines.cost_model / engines.backtest_metrics not importable — run from backend/")

    cm = CostModel()  # repo defaults: k_impact=0.0015, brokerage 20, STT 0.1% sell
    total_costs = 0.0

    def _adv_for(sym: str, rb: date) -> float | None:
        if adv_by_date is None:
            return adv.get(sym)  # legacy single ADV, unchanged
        day_adv = adv_by_date.get(rb, {})
        if sym not in day_adv:
            raise ValueError(f"no point-in-time ADV for {sym} at {rb}; refusing to substitute")
        return day_adv[sym]

    cash = float(budget)
    holdings: dict[str, float] = {}
    prev_equity: float | None = None
    prev_exec: date | None = None
    prev_basket: set[str] = set()

    period_rets: list[float] = []
    basket_gross_rets: list[float] = []
    universe_gross_rets: list[float] = []
    legs_per_period: list[int] = []
    turnover_per_period: list[float] = []
    baskets: list[tuple[date, list[str], int]] = []
    skipped: list[date] = []

    for rb in rebalance_dates_list:
        # ADV path: only names with a full point-in-time ADV window at rb are
        # rankable, so nothing is traded on a substituted impact cost.
        eligible = None if adv_by_date is None else set(adv_by_date.get(rb, {}))
        basket = top_quartile(closes, rb, k=k, lookback=lookback, eligible=eligible)
        exec_day = execution_day(closes, rb)
        if not basket or exec_day is None:
            skipped.append(rb)
            continue

        basket_set = set(basket)

        # Buys: names entering the basket (or the whole basket at t=0), sized
        # at budget/k split, filled at next-session open.
        buy_symbols = basket_set - prev_basket
        buy_notional = 0.0
        buy_costs = 0.0
        per_position = budget / max(len(basket), 1)
        for sym in sorted(buy_symbols):
            price = _last_price(opens[sym], exec_day) if opens is not None and sym in opens.columns else None
            if price is None or price <= 0:
                price = _last_price(closes[sym], exec_day)
            if price is None or price <= 0:
                continue
            qty = max(1, int(per_position // price))
            holdings[sym] = float(qty)
            buy_notional += float(qty) * price
            buy_costs += cm.total_cost(price=price, qty=float(qty), adv=_adv_for(sym, rb),
                                       spread_bps=spread_bps, side="BUY")

        # Sells: names leaving the basket, valued at next-session open.
        sell_symbols = prev_basket - basket_set
        sell_notional = 0.0
        sell_costs = 0.0
        for sym in sorted(sell_symbols):
            qty = holdings.pop(sym, 0.0)
            if qty <= 0:
                continue
            price = _last_price(opens[sym], exec_day) if opens is not None and sym in opens.columns else None
            if price is None or price <= 0:
                price = _last_price(closes[sym], exec_day)
            if price is None or price <= 0:
                continue
            sell_notional += float(qty) * price
            sell_costs += cm.total_cost(price=price, qty=float(qty), adv=_adv_for(sym, rb),
                                        spread_bps=spread_bps, side="SELL")

        if not holdings:
            skipped.append(rb)
            continue

        # Equity just after today's fills.
        holdings_value = 0.0
        position_values: dict[str, float] = {}
        for sym, qty in holdings.items():
            price = _last_price(opens[sym], exec_day) if opens is not None and sym in opens.columns else None
            if price is None or price <= 0:
                price = _last_price(closes[sym], exec_day)
            if price is None or price <= 0:
                continue
            holdings_value += float(qty) * price
            position_values[sym] = float(qty) * price
        cash = cash + sell_notional - sell_costs - buy_notional - buy_costs
        total_costs += buy_costs + sell_costs
        equity_after = cash + holdings_value
        if trace is not None:  # diagnostics only; output unaffected
            trace.append({"rebalance": rb.isoformat(), "exec_day": exec_day.isoformat(), "cash": cash,
                          "holdings_value": holdings_value, "equity": equity_after,
                          "n_positions": len(position_values), "position_values": position_values})

        if prev_equity is not None:
            period_rets.append(equity_after / prev_equity - 1.0)
        prev_equity = equity_after

        # Gross forward returns (win-alignment): basket vs all-universe,
        # measured fill-open(t-1) -> fill-open(t) across the holding period.
        if prev_exec is not None and prev_basket:
            basket_ret = _gross_forward_return(closes, opens, prev_basket, prev_exec, exec_day)
            universe_ret = _gross_forward_return(closes, opens, set(closes.columns), prev_exec, exec_day)
            if basket_ret is not None and universe_ret is not None:
                basket_gross_rets.append(basket_ret)
                universe_gross_rets.append(universe_ret)

        # Turnover accounting: only actual rotations (t > 0) count — the
        # initial entry is one-time, not per-rebalance turnover.
        if prev_basket:
            legs = len(sell_symbols) + len(buy_symbols)
            legs_per_period.append(legs)
            turnover = (len(sell_symbols) + len(buy_symbols)) / (2.0 * max(len(basket), 1))
            turnover_per_period.append(turnover)
        baskets.append((rb, basket, len(basket)))

        prev_exec = exec_day
        prev_basket = basket_set

    if prev_equity is None:
        raise RuntimeError("no rebalance was actionable — no price data?")

    # k from the first ACTIONABLE rebalance (the first scheduled date may
    # predate the 22-session lookback and rank no symbols).
    k_used = len(baskets[0][1]) if baskets else max(1, len(rebalance_dates_list))
    result = {
        "k_used": k_used,
        "n_rebalances": len(baskets),
        "n_period_returns": len(period_rets),
        "skipped_rebalances": [d.isoformat() for d in skipped],
        "period_returns": period_rets,
        "basket_gross_returns": basket_gross_rets,
        "universe_gross_returns": universe_gross_rets,
        "legs_per_period": legs_per_period,
        "turnover_per_period": turnover_per_period,
        "baskets": baskets,
        "win_alignment_pct": _beats_market_rate(basket_gross_rets, universe_gross_rets),
        "avg_legs_per_rebalance": float(sum(legs_per_period) / len(legs_per_period)) if legs_per_period else 0.0,
        "avg_turnover_fraction": float(sum(turnover_per_period) / len(turnover_per_period)) if turnover_per_period else 0.0,
        "final_equity": prev_equity,
    }
    if adv_by_date is not None:
        result["total_costs"] = total_costs
    return result


def _gross_forward_return(closes, opens, symbols: set[str], day_from: date, day_to: date) -> float | None:
    """Equal-weighted mean of open(day_to)/open(day_from) - 1 over symbols with prices on both days."""
    rets = []
    for sym in sorted(symbols):
        if sym not in closes.columns:
            continue
        p0 = _last_price(opens[sym], day_from) if opens is not None and sym in opens.columns else None
        p1 = _last_price(opens[sym], day_to) if opens is not None and sym in opens.columns else None
        if p0 is None or p1 is None or p0 <= 0:
            p0 = _last_price(closes[sym], day_from)
            p1 = _last_price(closes[sym], day_to)
        if p0 is None or p1 is None or p0 <= 0:
            continue
        rets.append(p1 / p0 - 1.0)
    if not rets:
        return None
    return float(sum(rets) / len(rets))


def _beats_market_rate(basket_rets: list[float], universe_rets: list[float]) -> float:
    aligned = [(b, u) for b, u in zip(basket_rets, universe_rets) if u is not None and b is not None]
    if not aligned:
        return 0.0
    wins = sum(1 for b, u in aligned if b > u)
    return float(wins / len(aligned) * 100.0)


# ---------------------------------------------------------------------------
# Corrected simulator (Amendment 1): equal weight of current equity
# ---------------------------------------------------------------------------

CASH_TARGET_FRACTION = 0.005  # cash after fills is aimed at the middle of the allowed [0, 1%] band
MIN_TRADE_FRACTION = 1e-9  # trades below this share of equity are not executed (no brokerage on dust)


def _open_px(opens: pd.DataFrame | None, sym: str, day: date) -> float | None:
    """Open on `day` for one symbol, or None. No fallback to close: a missing open is not tradeable."""
    if opens is None or sym not in opens.columns or pd.Timestamp(day) not in opens.index:
        return None
    val = float(opens.at[pd.Timestamp(day), sym])
    return val if math.isfinite(val) and val > 0 else None


def _carry_px(closes: pd.DataFrame, opens: pd.DataFrame | None, sym: str, day: date,
              *, prior_close: bool = False) -> float:
    """Valuation price: open on `day`, else the last close on/before `day` (carry)."""
    px = _open_px(opens, sym, day)
    if px is None:
        if prior_close:
            earlier = closes.loc[closes.index < pd.Timestamp(day), sym].dropna()
            px = float(earlier.iloc[-1]) if len(earlier) else None
        else:
            px = _last_price(closes[sym], day)
    if px is None:
        raise ValueError(f"no price at all for held {sym} on {day}")
    return px


def _rebalance_step(state: dict, basket: list[str], adv_now: dict[str, float], closes: pd.DataFrame,
                    opens: pd.DataFrame, day: date, cost_model, spread_bps: float,
                    *, prior_close_carry: bool = False) -> tuple[dict, dict] | None:
    """
    One rebalance at `day`'s open. E = cash + holdings at `day` (carried where no open).
    Each tradeable basket name is set to an equal share of E; trades are the differences
    only; sells remove held names that left the basket. Cash after fills and costs is
    aimed at CASH_TARGET_FRACTION*E and must land in [0, 1%] of E. Returns None when no
    basket name can be traded on `day`.
    """
    cash0 = float(state["cash"])
    holdings = dict(state["holdings"])
    carry = {s: _carry_px(closes, opens, s, day, prior_close=prior_close_carry) for s in holdings}
    E0 = cash0 + sum(q * carry[s] for s, q in holdings.items())

    tradeable = [s for s in basket if _open_px(opens, s, day) is not None]
    skipped_buys = [s for s in basket if s not in tradeable]
    if not tradeable:
        return None
    held_open = [s for s in holdings if _open_px(opens, s, day) is not None]
    carried = sorted(s for s in holdings if s not in held_open)  # no open: carried, not traded
    carried_value = sum(holdings[s] * carry[s] for s in carried)
    sells = sorted(s for s in held_open if s not in basket)
    n = len(tradeable)

    def plan(frac: float):
        each = (frac * E0 - carried_value) / n
        legs = []  # (sym, side, price, notional, new_qty)
        for s in tradeable:
            px = _open_px(opens, s, day)
            cur = holdings.get(s, 0.0) * px
            diff = each - cur
            if abs(diff) > MIN_TRADE_FRACTION * E0:
                legs.append((s, "BUY" if diff > 0 else "SELL", px, abs(diff), each / px))
        for s in sells:
            px = _open_px(opens, s, day)
            notional = holdings[s] * px
            if notional > MIN_TRADE_FRACTION * E0:
                legs.append((s, "SELL", px, notional, 0.0))
        costs = 0.0
        for s, side, px, notional, _ in legs:
            if s not in adv_now:
                raise ValueError(f"no point-in-time ADV for {s} at {day}; refusing to substitute")
            costs += cost_model.total_cost(price=px, qty=notional / px, adv=adv_now[s],
                                           spread_bps=spread_bps, side=side)
        return legs, costs

    frac = 1.0 - CASH_TARGET_FRACTION
    for _ in range(200):  # fixed point: costs depend on the trade sizes, which depend on frac
        _, costs = plan(frac)
        new_frac = 1.0 - (costs + CASH_TARGET_FRACTION * E0) / E0
        if abs(new_frac - frac) < 1e-15:
            break
        frac = new_frac
    legs, costs = plan(frac)

    cash = cash0
    traded = 0.0
    for s, side, px, notional, new_qty in legs:
        cash += notional if side == "SELL" else -notional
        traded += notional
        if s in sells:
            holdings.pop(s, None)
        else:
            holdings[s] = new_qty
    cash -= costs
    if not (-1e-9 * E0 <= cash <= 0.01 * E0):
        raise RuntimeError(f"cash after fills {cash:.2f} outside [0, 1%] of equity {E0:.2f} at {day}")
    new_state = {"cash": cash, "holdings": {s: q for s, q in holdings.items() if q > 0}}
    info = {"equity_pre": E0, "traded_notional": traded, "costs": costs,
            "carried": carried, "skipped_buys": skipped_buys, "n_trades": len(legs)}
    if prior_close_carry:
        info["traded_names"] = [s for s, _, _, _, _ in legs]
    return new_state, info


def simulate_rebalanced(
    closes: pd.DataFrame,
    opens: pd.DataFrame,
    adv_by_date: dict[date, dict[str, float]],
    rebalance_dates_list: list[date],
    *,
    cost_model,
    budget: float = DEFAULT_BUDGET_INR,
    spread_bps: float = ASSUMED_SPREAD_BPS,
    k: int | None = None,
    lookback: int = LOOKBACK_TRADING_DAYS,
    trace: list | None = None,
    select=None,
    prior_close_carry: bool = False,
    held_adv_history: dict[date, dict[str, float]] | None = None,
    check_rebalance=None,
    compute_period_returns: bool = True,
) -> dict:
    """
    Amendment 1 simulator. Same signal, eligibility (point-in-time ADV, full 63-session
    window), schedule and next-open execution as the registered path. Sizing is equal
    weight of current equity at every rebalance, with fractional shares. `cost_model` is
    passed in so the caller sets brokerage. Period return = equity after fills at t /
    equity after fills at t-1 - 1, with equity valued at each execution-day open.

    select(closes, rebalance_date, eligible) -> ordered basket. None (default) uses the
    top-quartile selection by lookback return, unchanged.
    Momentum opts into prior-close carry, earlier complete held-name ADV, and
    a check_rebalance(row) hook. It defers returns until both sides pass every gate.
    """
    state = {"cash": float(budget), "holdings": {}}
    prev_equity: float | None = None
    period_rets: list[float] = []
    baskets: list[tuple[date, list[str], int]] = []
    skipped: list[date] = []
    total_costs = 0.0
    rows: list[dict] = []
    carried_log: list[dict] = []
    skipped_buy_log: list[dict] = []
    adv_uses, resumed_trades, carry_uses, dropped_targets = [], [], [], []
    previously_carried: set[str] = set()

    for rb in rebalance_dates_list:
        eligible = set(adv_by_date.get(rb, {}))
        if select is None:
            basket = top_quartile(closes, rb, k=k, lookback=lookback, eligible=eligible)
        else:
            basket = list(select(closes, rb, eligible))
            if not set(basket) <= eligible:
                raise ValueError(f"select returned names without point-in-time ADV at {rb}")
        exec_day = execution_day(closes, rb)
        if not basket or exec_day is None:
            skipped.append(rb)
            continue
        adv_now = adv_by_date[rb]
        fallbacks = {}
        if held_adv_history is not None:
            adv_now = dict(adv_now)
            for sym in state["holdings"]:
                if sym in adv_now or _open_px(opens, sym, exec_day) is None:
                    continue
                for source in sorted((d for d in held_adv_history if d < rb), reverse=True):
                    if sym in held_adv_history[source]:
                        adv_now[sym] = held_adv_history[source][sym]
                        fallbacks[sym] = {"rebalance": rb.isoformat(), "symbol": sym,
                                          "source_date": source.isoformat(), "adv": adv_now[sym]}
                        break
                else:
                    raise ValueError(f"no earlier complete ADV for held {sym} at {rb}")
        held_before = set(state["holdings"])
        step = _rebalance_step(state, basket, adv_now, closes, opens, exec_day, cost_model, spread_bps,
                               prior_close_carry=prior_close_carry)
        if step is None:
            skipped.append(rb)
            continue
        state, info = step
        holdings_value = 0.0
        position_values: dict[str, float] = {}
        for s, q in state["holdings"].items():
            v = q * _carry_px(closes, opens, s, exec_day, prior_close=prior_close_carry)
            position_values[s] = v
            holdings_value += v
        equity = state["cash"] + holdings_value
        total_costs += info["costs"]
        for s in info["carried"]:
            carried_log.append({"rebalance": rb.isoformat(), "symbol": s})
        for s in info["skipped_buys"]:
            skipped_buy_log.append({"rebalance": rb.isoformat(), "symbol": s})
        row = {"rebalance": rb.isoformat(), "exec_day": exec_day.isoformat(), "equity": equity,
               "cash": state["cash"], "holdings_value": holdings_value,
               "invested_fraction": holdings_value / equity, "n_positions": len(position_values),
               "traded_notional": info["traded_notional"], "costs": info["costs"],
               "turnover": info["traded_notional"] / info["equity_pre"], "position_values": position_values}
        if check_rebalance is not None:
            check_rebalance(row)
        if compute_period_returns and prev_equity is not None:
            period_rets.append(equity / prev_equity - 1.0)
        prev_equity = equity
        if prior_close_carry:
            traded = set(info["traded_names"])
            adv_uses.extend(fallbacks[s] for s in sorted(traded & fallbacks.keys()))
            for sym in sorted(previously_carried & traded):
                resumed_trades.append({"rebalance": rb.isoformat(), "symbol": sym,
                                       "action": "resized" if sym in basket else "sold"})
            for sym in info["carried"]:
                earlier = closes.loc[closes.index < pd.Timestamp(exec_day), sym].dropna()
                carry_uses.append({"rebalance": rb.isoformat(), "exec_day": exec_day.isoformat(),
                                   "symbol": sym, "source_date": earlier.index[-1].date().isoformat(),
                                   "price": float(earlier.iloc[-1]), "value": position_values[sym]})
            for sym in info["skipped_buys"]:
                if sym not in held_before:
                    dropped_targets.append({"rebalance": rb.isoformat(), "symbol": sym})
            previously_carried = set(info["carried"])
        rows.append(row)
        if trace is not None:
            trace.append(row)
        baskets.append((rb, basket, len(basket)))

    if prev_equity is None:
        raise RuntimeError("no rebalance was actionable — no price data?")
    turns = [r["turnover"] for r in rows[1:]]
    return {
        "k_used": len(baskets[0][1]) if baskets else 0,
        "n_rebalances": len(baskets),
        "period_returns": period_rets,
        "baskets": baskets,
        "skipped_rebalances": [d.isoformat() for d in skipped],
        "trace": rows,
        "total_costs": total_costs,
        "avg_turnover_after_entry": float(sum(turns) / len(turns)) if turns else 0.0,
        "carried": carried_log,
        "skipped_buys": skipped_buy_log,
        "final_equity": prev_equity,
        **({"input_uses": {"held_adv_fallback": adv_uses, "unheld_target_no_open": dropped_targets,
                           "held_no_open": carry_uses, "resumed_held_trades": resumed_trades,
                           "carried_invested": [{"rebalance": r["rebalance"], "symbol": r["symbol"],
                                                  "value": r["value"]} for r in carry_uses]}}
           if prior_close_carry else {}),
    }


# ---------------------------------------------------------------------------
# Metrics (repo canonical functions)
# ---------------------------------------------------------------------------

def compute_metrics(period_returns: list[float], periods_per_year: int) -> dict:
    """Sharpe + stationary-bootstrap CI via the repo's canonical functions."""
    if not REPO_ENGINES_AVAILABLE:
        raise RuntimeError("engines.backtest_metrics not importable — run from backend/")
    sharpe = compute_sharpe(period_returns, periods_per_year=periods_per_year)
    ci = stationary_bootstrap_sharpe_ci(period_returns, periods_per_year=periods_per_year)
    return {
        "sharpe": float(sharpe),
        "ci_lower": float(ci["ci_lower"]),
        "ci_upper": float(ci["ci_upper"]),
        "ci_n_bootstrap": int(ci["n_bootstrap"]),
        "ci_n_obs": int(ci["n_obs"]),
        "ci_mean_block_length": 10,
        "ci_seed": 42,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_hypothesis() -> str:
    path = os.path.join(_SANDBOX_DIR, "hypothesis.md")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return "(hypothesis.md not found — expected at backend/sandbox/hypothesis.md)"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AlphaCore top-quartile basket backtest (monthly/quarterly)")
    p.add_argument("--frequency", choices=["monthly", "quarterly"], default="monthly")
    p.add_argument("--budget", type=float, default=DEFAULT_BUDGET_INR)
    p.add_argument("--spread-bps", type=float, default=ASSUMED_SPREAD_BPS)
    p.add_argument("--as-of", type=str, default=None, help="YYYY-MM-DD data cutoff (default: today)")
    p.add_argument("--fetch-period-days", type=int, default=FETCH_PERIOD_DAYS)
    p.add_argument("--k", type=int, default=None,
                   help="basket size; default: top-quartile (n_ranked // 4, i.e. 12 of 49)")
    p.add_argument("--lookback", type=int, default=LOOKBACK_TRADING_DAYS,
                   help=f"signal lookback in trading sessions (default: {LOOKBACK_TRADING_DAYS})")
    p.add_argument("--start", type=str, default=None,
                   help="YYYY-MM-DD schedule start; rebalances before this date are excluded "
                        "(split-sample runs keep prior history for the first ranking)")
    p.add_argument("--cache", type=str, default=None,
                   help="path to a closes/adv/opens pickle cache; loads it if present, otherwise "
                        "fetches fresh and saves it (allows identical data across runs)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()

    # Pre-committed hypothesis BEFORE any data is pulled (same convention as harness.py).
    print("=" * 78)
    print("PRECOMMITTED HYPOTHESIS (stated before any price data is pulled)")
    print("=" * 78)
    print(_load_hypothesis())
    print("=" * 78)

    ppy = 12 if args.frequency == "monthly" else 4
    start_date = date.fromisoformat(args.start) if args.start else None
    k_label = "top-quartile (auto)" if args.k is None else f"fixed {args.k}"
    print(f"\n[RUN] basket_backtest frequency={args.frequency} (periods/yr={ppy}) "
          f"budget={args.budget:,.0f} INR spread_bps={args.spread_bps} as_of={as_of} "
          f"k={k_label} lookback={args.lookback} start={start_date or 'fetch-start'}")
    print("[RUN] cost model: repo CostModel defaults "
          "(k_impact=0.0015, brokerage Rs 20/trade, STT 0.1% sell-side)")

    if not REPO_ENGINES_AVAILABLE:
        print("[FATAL] engines.cost_model / engines.backtest_metrics not importable — "
              "run from backend/ with python3.11", file=sys.stderr)
        return 2

    closes, adv, opens = None, None, None
    if args.cache and os.path.exists(args.cache):
        try:
            with open(args.cache, "rb") as fh:
                blob = pickle.load(fh)
            closes, adv, opens = blob["closes"], blob["adv"], blob["opens"]
            print(f"[DATA] loaded closes/adv/opens from cache {args.cache} "
                  f"({len(closes)} sessions, {len(closes.columns)} symbols)")
            # Clip to as_of so split-sample runs see only their half's data
            # (identical to what a fresh fetch with this as_of would return).
            closes = closes[closes.index <= pd.Timestamp(as_of)]
            if opens is not None and len(opens):
                opens = opens[opens.index <= pd.Timestamp(as_of)]
        except Exception as exc:
            print(f"[DATA] cache load failed ({exc}); refetching fresh")
            closes, adv, opens = None, None, None

    if closes is None or closes.empty:
        print(f"\n[DATA] Fetching daily bars for {len(UNIVERSE_49)}-symbol universe (Nifty 50 minus SBILIFE), "
              f"{args.fetch_period_days} days...")
        closes, adv, opens = fetch_daily_bars(UNIVERSE_49, as_of=as_of,
                                              fetch_period_days=args.fetch_period_days,
                                              include_open=True)
        if args.cache:
            with open(args.cache, "wb") as fh:
                pickle.dump({"closes": closes, "adv": adv, "opens": opens}, fh)
            print(f"[DATA] cached closes/adv/opens -> {args.cache}")
    if closes is None or closes.empty:
        print("[FATAL] no price data; aborting")
        return 1

    end = closes.index.max().date()
    print(f"[DATA] data window: {closes.index.min().date()} -> {end} ({len(closes)} sessions)")

    schedule = monthly_rebalance_dates(closes, end) if args.frequency == "monthly" else quarterly_rebalance_dates(closes, end)
    if start_date is not None:
        schedule = [d for d in schedule if d >= start_date]
    window_desc = f"{schedule[0]} -> {schedule[-1]}" if schedule else "(empty)"
    print(f"[SCHEDULE] {len(schedule)} {args.frequency} rebalance dates "
          f"(last trading day of {'month' if args.frequency == 'monthly' else 'quarter-end month'}), "
          f"window {window_desc}")

    res = simulate(closes, adv, opens, schedule, budget=args.budget, spread_bps=args.spread_bps,
                   k=args.k, lookback=args.lookback)
    metrics = compute_metrics(res["period_returns"], ppy)

    print(f"\n[RESULT] k = {res['k_used']} (requested k={k_label}, lookback={args.lookback} sessions; "
          f"basket of {res['k_used']} from {len(UNIVERSE_49)}-symbol universe)")
    print(f"[RESULT] actionable rebalances: {res['n_rebalances']} "
          f"| skipped (no data yet): {len(res['skipped_rebalances'])}")
    print(f"[RESULT] per-rebalance period returns (net of costs): {len(res['period_returns'])}")
    print(f"[RESULT] sharpe (per-rebalance, annualized x{ppy}) = {metrics['sharpe']:.4f}")
    print(f"[RESULT] 95% CI (stationary bootstrap, n_boot={metrics['ci_n_bootstrap']}, "
          f"block_len=10, seed=42) = [{metrics['ci_lower']:.4f}, {metrics['ci_upper']:.4f}]")
    print(f"[RESULT] win-alignment (beats equal-weight all-universe, gross) = {res['win_alignment_pct']:.1f}% "
          f"({len(res['basket_gross_returns'])} periods)")
    print(f"[RESULT] avg legs per rebalance = {res['avg_legs_per_rebalance']:.2f} "
          f"| avg one-sided turnover fraction = {res['avg_turnover_fraction']:.3f}")
    print(f"[RESULT] final equity = {res['final_equity']:,.0f} INR from {args.budget:,.0f} INR "
          f"({(res['final_equity'] / args.budget - 1) * 100:.1f}% total)")

    print("\n[PER-PERIOD] rb_date | basket_size | legs | turnover | basket_gross | universe_gross | net_period_ret")
    print("[PER-PERIOD] (gross/universe/net/legs/turnover rows are the holding-period values ENDING at that rebalance)")
    for i, (rb, basket, size) in enumerate(res["baskets"]):
        leg = res["legs_per_period"][i - 1] if i > 0 and i - 1 < len(res["legs_per_period"]) else None
        turn = res["turnover_per_period"][i - 1] if i > 0 and i - 1 < len(res["turnover_per_period"]) else None
        bg = res["basket_gross_returns"][i - 1] if i > 0 and i - 1 < len(res["basket_gross_returns"]) else None
        ug = res["universe_gross_returns"][i - 1] if i > 0 and i - 1 < len(res["universe_gross_returns"]) else None
        net = res["period_returns"][i - 1] if i > 0 and i - 1 < len(res["period_returns"]) else None
        leg_s = str(leg) if leg is not None else "-"
        turn_s = f"{turn:.3f}" if turn is not None else "-"
        bg_s = f"{bg * 100:.2f}%" if bg is not None else "-"
        ug_s = f"{ug * 100:.2f}%" if ug is not None else "-"
        net_s = f"{net * 100:.2f}%" if net is not None else "-"
        print(f"[PER-PERIOD] {rb} | {size} | {leg_s} | {turn_s} | {bg_s} | {ug_s} | {net_s}")

    print("\n[JSON] " + json.dumps({
        "config": f"basket-topquartile-{args.frequency}",
        "k": res["k_used"],
        "k_requested": args.k,
        "lookback": args.lookback,
        "start": args.start,
        "frequency": args.frequency,
        "periods_per_year": ppy,
        "universe_size": len(UNIVERSE_49),
        "n_rebalances": res["n_rebalances"],
        "n_period_returns": len(res["period_returns"]),
        "data_window": [closes.index.min().date().isoformat(), end.isoformat()],
        "cost_model": {"k_impact": 0.0015, "brokerage_per_trade": 20.0, "stt_rate": 0.001,
                       "spread_bps": args.spread_bps},
        "sharpe": metrics["sharpe"],
        "ci_lower": metrics["ci_lower"],
        "ci_upper": metrics["ci_upper"],
        "win_alignment_pct": res["win_alignment_pct"],
        "avg_legs_per_rebalance": res["avg_legs_per_rebalance"],
        "avg_turnover_fraction": res["avg_turnover_fraction"],
        "final_equity": res["final_equity"],
    }, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
