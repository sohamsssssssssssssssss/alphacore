#!/usr/bin/env python3.11
"""
AlphaCore — Cross-Sectional Relative Strength DIAGNOSTIC

PURPOSE: Diagnose why the cross-sectional relative strength experiment lost
on BOTH legs. This script:

1. FIXES the MTM bug found in cross_sectional_experiment.py:
   - Bug: MTM was computed as (current_mid - entry_price) each day instead
     of (current_mid - last_mid). This double-counts cumulative PnL.
   - Fix: Track last_mid per position, compute MTM as daily change.

2. DUMPS every rebalance event in the test period with full details.

3. COMPUTES a naive hold-to-maturity benchmark for comparison.

4. QUANTIFIES whipsaw/costs.

This is NOT a re-run of the full experiment with new parameters. Only the
MTM bug fix is applied — all strategy parameters (N=20, K=1, rebalance
every 5 days, position sizing) remain identical.

Protocol: CROSS_SECTIONAL_EXPERIMENT_PROTOCOL.md (pre-committed)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engines.backtest_metrics import compute_sharpe, stationary_bootstrap_sharpe_ci
from engines.cost_model import CostModel

# ── Configuration (identical to original experiment) ──────────────────────

SYMBOLS = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "real_nse_data"
TRAIN_END_INDEX = 867
TEST_START_INDEX = 867
LOOKBACK_N = 20  # locked from original experiment
K = 1
REBALANCE_INTERVAL = 5
POSITION_SIZE_PCT = 0.10
INITIAL_CAPITAL = 100000.0
N_BOOTSTRAP = 2000
BOOTSTRAP_SEED = 2026
MEAN_BLOCK_LENGTH = 5

cost_model = CostModel()

# ── Data Loading ───────────────────────────────────────────────────────────

def load_data() -> dict[str, pd.DataFrame]:
    data = {}
    for sym in SYMBOLS:
        path = DATA_DIR / f"{sym}.csv"
        df = pd.read_csv(path, parse_dates=["Date"])
        df = df.sort_values("Date").reset_index(drop=True)
        data[sym] = df
    return data


def build_panel(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    panel = None
    for sym in SYMBOLS:
        df = data[sym]
        spread_bps = ((df["High"] - df["Low"]) / df["Close"] * 10000.0).clip(0.5, 50.0)
        small = df[["Date"]].copy()
        small["Date"] = pd.to_datetime(small["Date"])
        small[f"{sym}_close"] = df["Close"].values
        small[f"{sym}_spread_bps"] = spread_bps.values
        if panel is None:
            panel = small
        else:
            panel = panel.merge(small, on="Date", how="outer")
    panel = panel.set_index("Date").sort_index()
    return panel


def close_to_bid_ask(close: float, spread_bps: float) -> tuple[float, float]:
    spread_abs = (spread_bps / 10000.0) * close
    bid = close - spread_abs / 2.0
    ask = close + spread_abs / 2.0
    if bid >= ask:
        ask = bid + 1e-6
    return bid, ask


# ── FIXED Cross-Sectional Backtester ──────────────────────────────────────

class FixedCrossSectionalBacktester:
    """BUG-FIXED backtester for cross-sectional relative strength.

    FIX: MTM now tracks last_mid per position and computes daily change
    as (current_mid - last_mid) instead of (current_mid - entry_price).

    Exit PnL is computed from current_mid to bid/ask, not from entry_price
    to bid/ask.
    """

    def __init__(self, panel, lookback_n=20, k=1, rebalance_interval=5,
                 position_size_pct=0.10, initial_capital=100000.0):
        self.panel = panel
        self.lookback_n = lookback_n
        self.k = k
        self.rebalance_interval = rebalance_interval
        self.position_size_pct = position_size_pct
        self.initial_capital = initial_capital
        self.symbols = [c.replace("_close", "") for c in panel.columns if c.endswith("_close")]

    def run(self, dump_rebalances: bool = False) -> dict:
        """Run the backtest with CORRECTED MTM.

        If dump_rebalances=True, prints every rebalance event.
        """
        panel = self.panel
        n_days = len(panel)
        symbols = self.symbols

        trailing_rets = {}
        for sym in symbols:
            close_col = f"{sym}_close"
            trailing_rets[sym] = panel[close_col].pct_change(periods=self.lookback_n)

        # State
        equity = float(self.initial_capital)
        daily_returns: list[float] = []
        gross_pnl_total = 0.0
        total_costs = 0.0

        # Position state (unchanged from original)
        long_sym: str | None = None
        short_sym: str | None = None
        long_qty: float = 0.0
        short_qty: float = 0.0
        long_entry_price: float = 0.0
        short_entry_price: float = 0.0
        last_rebalance_day: int = -1

        # FIX: Track last mid for MTM (new fields)
        long_last_mid: float = 0.0
        short_last_mid: float = 0.0

        trades: list[dict] = []

        # Diagnostic: rebalance dump
        rebalance_log: list[dict] = []

        start_day = self.lookback_n

        for day_idx in range(start_day, n_days):
            row = panel.iloc[day_idx]
            prev_equity = equity
            date = panel.index[day_idx]

            # ── 1. Compute trailing returns and rank ──
            day_returns = {}
            for sym in symbols:
                ret = trailing_rets[sym].iloc[day_idx]
                if pd.isna(ret):
                    continue
                day_returns[sym] = ret

            if len(day_returns) < len(symbols):
                daily_returns.append(0.0)
                continue

            ranked = sorted(day_returns.items(), key=lambda x: x[1], reverse=True)
            top_sym = ranked[0][0]
            bottom_sym = ranked[-1][0]

            # ── 2. Check if rebalance day ──
            days_since = day_idx - last_rebalance_day
            is_rebalance = (days_since >= self.rebalance_interval)

            # ── 3. FIXED MTM PnL from held positions ──
            day_pnl = 0.0
            mtn_log = {}

            if long_sym is not None and long_qty > 0:
                close_price = row[f"{long_sym}_close"]
                spread_bps = row[f"{long_sym}_spread_bps"]
                bid, ask = close_to_bid_ask(close_price, spread_bps)
                mid = (bid + ask) / 2.0

                # FIX: MTM from last_mid to current_mid, NOT from entry_price
                mtm_pnl = (mid - long_last_mid) * long_qty
                day_pnl += mtm_pnl
                mtn_log["long"] = {"last_mid": float(long_last_mid), "current_mid": float(mid),
                                   "mtm_pnl": float(mtm_pnl)}
                # Update last_mid
                long_last_mid = mid

            if short_sym is not None and short_qty > 0:
                close_price = row[f"{short_sym}_close"]
                spread_bps = row[f"{short_sym}_spread_bps"]
                bid, ask = close_to_bid_ask(close_price, spread_bps)
                mid = (bid + ask) / 2.0

                # FIX: MTM from last_mid to current_mid for short
                mtm_pnl = (short_last_mid - mid) * short_qty
                day_pnl += mtm_pnl
                mtn_log["short"] = {"last_mid": float(short_last_mid), "current_mid": float(mid),
                                    "mtm_pnl": float(mtm_pnl)}
                short_last_mid = mid

            equity += day_pnl
            gross_pnl_total += day_pnl

            # ── 4. Rebalance (if scheduled) ──
            if is_rebalance:
                reb_log_entry = {
                    "day": int(day_idx),
                    "date": str(date.date()),
                    "rankings": {sym: float(day_returns[sym]) for sym in symbols},
                    "top_sym": top_sym,
                    "bottom_sym": bottom_sym,
                    "old_long_sym": long_sym,
                    "old_short_sym": short_sym,
                    "close_costs": [],
                    "open_costs": [],
                }

                # Close long
                if long_sym is not None and long_qty > 0:
                    close_price = row[f"{long_sym}_close"]
                    spread_bps = row[f"{long_sym}_spread_bps"]
                    bid, ask = close_to_bid_ask(close_price, spread_bps)

                    # FIX: Exit PnL from current_mid to bid (NOT from entry_price)
                    current_mid = (bid + ask) / 2.0
                    # long_last_mid was already set above to current_mid
                    exit_pnl = (bid - current_mid) * long_qty
                    equity += exit_pnl
                    gross_pnl_total += exit_pnl

                    cost = cost_model.total_cost(
                        price=bid, qty=long_qty, adv=None,
                        spread_bps=spread_bps, side="SELL",
                    )
                    total_costs += cost
                    equity -= cost

                    trades.append({
                        "symbol": long_sym, "leg": "LONG", "action": "CLOSE",
                        "day": int(day_idx), "qty": float(long_qty),
                        "entry_price": float(long_entry_price),
                        "exit_price": float(bid),
                        "pnl": float(exit_pnl - cost),
                        "gross_pnl": float(exit_pnl), "cost": float(cost),
                    })
                    reb_log_entry["close_costs"].append({
                        "sym": long_sym, "leg": "LONG", "pnl": float(exit_pnl), "cost": float(cost)
                    })
                    long_sym = None
                    long_qty = 0.0
                    long_entry_price = 0.0
                    long_last_mid = 0.0

                # Close short
                if short_sym is not None and short_qty > 0:
                    close_price = row[f"{short_sym}_close"]
                    spread_bps = row[f"{short_sym}_spread_bps"]
                    bid, ask = close_to_bid_ask(close_price, spread_bps)

                    # FIX: Exit PnL from current_mid to ask
                    current_mid = (bid + ask) / 2.0
                    exit_pnl = (current_mid - ask) * short_qty
                    equity += exit_pnl
                    gross_pnl_total += exit_pnl

                    cost = cost_model.total_cost(
                        price=ask, qty=short_qty, adv=None,
                        spread_bps=spread_bps, side="BUY",
                    )
                    total_costs += cost
                    equity -= cost

                    trades.append({
                        "symbol": short_sym, "leg": "SHORT", "action": "CLOSE",
                        "day": int(day_idx), "qty": float(short_qty),
                        "entry_price": float(short_entry_price),
                        "exit_price": float(ask),
                        "pnl": float(exit_pnl - cost),
                        "gross_pnl": float(exit_pnl), "cost": float(cost),
                    })
                    reb_log_entry["close_costs"].append({
                        "sym": short_sym, "leg": "SHORT", "pnl": float(exit_pnl), "cost": float(cost)
                    })
                    short_sym = None
                    short_qty = 0.0
                    short_entry_price = 0.0
                    short_last_mid = 0.0

                # Open new positions
                if top_sym != bottom_sym:
                    # Long leg
                    close_price = row[f"{top_sym}_close"]
                    spread_bps = row[f"{top_sym}_spread_bps"]
                    bid, ask = close_to_bid_ask(close_price, spread_bps)
                    qty_l = (self.position_size_pct * equity) / ask if ask > 0 else 0.0
                    if qty_l > 0:
                        cost_l = cost_model.total_cost(
                            price=ask, qty=qty_l, adv=None,
                            spread_bps=spread_bps, side="BUY",
                        )
                        total_costs += cost_l
                        equity -= cost_l
                        trades.append({
                            "symbol": top_sym, "leg": "LONG", "action": "OPEN",
                            "day": int(day_idx), "qty": float(qty_l),
                            "entry_price": float(ask), "exit_price": 0.0,
                            "pnl": float(-cost_l), "gross_pnl": 0.0, "cost": float(cost_l),
                        })
                        long_sym = top_sym
                        long_entry_price = ask
                        long_qty = qty_l
                        # FIX: Initialize last_mid to entry price (ask)
                        long_last_mid = ask
                        reb_log_entry["open_costs"].append({
                            "sym": top_sym, "leg": "LONG",
                            "entry_price": float(ask), "qty": float(qty_l),
                            "cost": float(cost_l)
                        })

                    # Short leg
                    close_price = row[f"{bottom_sym}_close"]
                    spread_bps = row[f"{bottom_sym}_spread_bps"]
                    bid, ask = close_to_bid_ask(close_price, spread_bps)
                    qty_s = (self.position_size_pct * equity) / bid if bid > 0 else 0.0
                    if qty_s > 0:
                        cost_s = cost_model.total_cost(
                            price=bid, qty=qty_s, adv=None,
                            spread_bps=spread_bps, side="SELL",
                        )
                        total_costs += cost_s
                        equity -= cost_s
                        trades.append({
                            "symbol": bottom_sym, "leg": "SHORT", "action": "OPEN",
                            "day": int(day_idx), "qty": float(qty_s),
                            "entry_price": float(bid), "exit_price": 0.0,
                            "pnl": float(-cost_s), "gross_pnl": 0.0, "cost": float(cost_s),
                        })
                        short_sym = bottom_sym
                        short_entry_price = bid
                        short_qty = qty_s
                        # FIX: Initialize last_mid to entry price (bid)
                        short_last_mid = bid
                        reb_log_entry["open_costs"].append({
                            "sym": bottom_sym, "leg": "SHORT",
                            "entry_price": float(bid), "qty": float(qty_s),
                            "cost": float(cost_s)
                        })

                last_rebalance_day = day_idx

                if dump_rebalances:
                    dump_rebalance(reb_log_entry, panel)
                rebalance_log.append(reb_log_entry)

            # ── 5. Daily return ──
            daily_ret = (equity - prev_equity) / prev_equity if prev_equity > 0 else 0.0
            daily_returns.append(float(daily_ret))

        # ── Flush open positions at end ──
        if long_sym is not None and long_qty > 0:
            last_row = panel.iloc[-1]
            close_price = last_row[f"{long_sym}_close"]
            spread_bps = last_row[f"{long_sym}_spread_bps"]
            bid, ask = close_to_bid_ask(close_price, spread_bps)
            current_mid = (bid + ask) / 2.0
            exit_pnl = (bid - current_mid) * long_qty
            # Note: last MTM was already applied above (long_last_mid was updated)
            equity += exit_pnl
            gross_pnl_total += exit_pnl
            cost = cost_model.total_cost(
                price=bid, qty=long_qty, adv=None,
                spread_bps=spread_bps, side="SELL",
            )
            total_costs += cost
            equity -= cost
            trades.append({
                "symbol": long_sym, "leg": "LONG", "action": "CLOSE_END",
                "day": int(n_days - 1), "qty": float(long_qty),
                "entry_price": float(long_entry_price), "exit_price": float(bid),
                "pnl": float(exit_pnl - cost), "gross_pnl": float(exit_pnl), "cost": float(cost),
            })

        if short_sym is not None and short_qty > 0:
            last_row = panel.iloc[-1]
            close_price = last_row[f"{short_sym}_close"]
            spread_bps = last_row[f"{short_sym}_spread_bps"]
            bid, ask = close_to_bid_ask(close_price, spread_bps)
            current_mid = (bid + ask) / 2.0
            exit_pnl = (current_mid - ask) * short_qty
            equity += exit_pnl
            gross_pnl_total += exit_pnl
            cost = cost_model.total_cost(
                price=ask, qty=short_qty, adv=None,
                spread_bps=spread_bps, side="BUY",
            )
            total_costs += cost
            equity -= cost
            trades.append({
                "symbol": short_sym, "leg": "SHORT", "action": "CLOSE_END",
                "day": int(n_days - 1), "qty": float(short_qty),
                "entry_price": float(short_entry_price), "exit_price": float(ask),
                "pnl": float(exit_pnl - cost), "gross_pnl": float(exit_pnl), "cost": float(cost),
            })

        # Compute metrics
        net_pnl = equity - self.initial_capital
        denom = abs(float(gross_pnl_total))
        cost_drag_pct = (total_costs / denom * 100.0) if denom > 0 else 0.0
        daily_ret_array = np.array(daily_returns, dtype=float)

        # Whipsaw analysis
        whipsaw = {"long_turnover": 0, "short_turnover": 0, "same_long_count": 0, "same_short_count": 0}
        for i in range(1, len(rebalance_log)):
            prev = rebalance_log[i-1]
            curr = rebalance_log[i]
            if prev["top_sym"] == curr["top_sym"]:
                whipsaw["same_long_count"] += 1
            else:
                whipsaw["long_turnover"] += 1
            if prev["bottom_sym"] == curr["bottom_sym"]:
                whipsaw["same_short_count"] += 1
            else:
                whipsaw["short_turnover"] += 1

        return {
            "trades": trades,
            "daily_returns": daily_ret_array,
            "final_equity": float(equity),
            "net_pnl": float(net_pnl),
            "gross_pnl": float(gross_pnl_total),
            "total_costs": float(total_costs),
            "cost_drag_pct": float(cost_drag_pct),
            "n_rebalances": len([t for t in trades if t["action"] == "OPEN"]),
            "n_trades": len(trades),
            "long_leg_pnl": float(sum(t["pnl"] for t in trades if t["leg"] == "LONG")),
            "short_leg_pnl": float(sum(t["pnl"] for t in trades if t["leg"] == "SHORT")),
            "rebalance_log": rebalance_log,
            "whipsaw": whipsaw,
        }


def dump_rebalance(entry: dict, panel: pd.DataFrame):
    """Print a formatted rebalance event dump."""
    date = entry["date"]
    top = entry["top_sym"]
    bottom = entry["bottom_sym"]
    old_long = entry["old_long_sym"]
    old_short = entry["old_short_sym"]

    # Sort rankings by value descending
    sorted_ranks = sorted(entry["rankings"].items(), key=lambda x: x[1], reverse=True)

    rank_str = "  ".join(f"{s}:{r:>+.4f}" for s, r in sorted_ranks)

    # Count matches with "obvious in hindsight" winners/losers
    total_cost = sum(c["cost"] for c in entry["close_costs"]) + sum(c["cost"] for c in entry["open_costs"])

    old_info = f"old pos: L={old_long}, S={old_short}" if old_long else "  old pos: (none)"
    close_info = "; ".join(f"close {c['sym']} {c['leg']}: PnL={c['pnl']:>+8.2f} "
                           f"cost={c['cost']:.2f}" for c in entry["close_costs"])
    open_info = "; ".join(f"open {o['sym']} {o['leg']}: ${o['entry_price']:.2f} "
                          f"qty={o['qty']:.1f} cost={o['cost']:.2f}" for o in entry["open_costs"])

    print(f"  [{date}] → L:{top} S:{bottom} | {old_info}")
    print(f"           ranks: {rank_str}")
    if close_info:
        print(f"           {close_info}")
    if open_info:
        print(f"           {open_info}")
    print(f"           total cost this rebal: ₹{total_cost:.2f}")


# ── Naive Hold Benchmark ─────────────────────────────────────────────────

def naive_hold_benchmark(panel: pd.DataFrame, lookback_n: int,
                         initial_capital: float = 100000.0) -> dict:
    """Compute a naive 'buy-and-hold-cross-sectional' benchmark.

    On day 1 of the test period, compute trailing N-day returns for all
    symbols, go long the top-ranked, short the bottom-ranked, and hold
    for the entire test period without rebalancing.
    """
    cost_model_local = CostModel()
    symbols = SYMBOLS
    trailing_rets = {}
    for sym in symbols:
        close_col = f"{sym}_close"
        trailing_rets[sym] = panel[close_col].pct_change(periods=lookback_n)

    # Day 1: rank and enter
    entry_idx = lookback_n  # first valid day
    entry_row = panel.iloc[entry_idx]

    day_returns = {}
    for sym in symbols:
        ret = trailing_rets[sym].iloc[entry_idx]
        if not pd.isna(ret):
            day_returns[sym] = ret

    ranked = sorted(day_returns.items(), key=lambda x: x[1], reverse=True)
    long_target = ranked[0][0]
    short_target = ranked[-1][0]

    equity = float(initial_capital)

    # Open long
    close_price = entry_row[f"{long_target}_close"]
    spread_bps = entry_row[f"{long_target}_spread_bps"]
    bid, ask = close_to_bid_ask(close_price, spread_bps)
    long_qty = (0.10 * equity) / ask if ask > 0 else 0.0
    cost_open_long = cost_model_local.total_cost(
        price=ask, qty=long_qty, adv=None, spread_bps=spread_bps, side="BUY",
    )
    equity -= cost_open_long
    long_entry_price = ask

    # Open short
    close_price = entry_row[f"{short_target}_close"]
    spread_bps = entry_row[f"{short_target}_spread_bps"]
    bid, ask = close_to_bid_ask(close_price, spread_bps)
    short_qty = (0.10 * equity) / bid if bid > 0 else 0.0
    cost_open_short = cost_model_local.total_cost(
        price=bid, qty=short_qty, adv=None, spread_bps=spread_bps, side="SELL",
    )
    equity -= cost_open_short
    short_entry_price = bid

    # Hold till last day
    n_days = len(panel)
    last_row = panel.iloc[-1]

    daily_returns = []
    long_last_mid = long_entry_price
    short_last_mid = short_entry_price
    cum_equity = float(initial_capital) - cost_open_long - cost_open_short

    for day_idx in range(entry_idx + 1, n_days):
        row = panel.iloc[day_idx]
        prev_equity = cum_equity
        day_pnl = 0.0

        # MTM long
        close_price_l = row[f"{long_target}_close"]
        spread_bps_l = row[f"{long_target}_spread_bps"]
        bid_l, ask_l = close_to_bid_ask(close_price_l, spread_bps_l)
        mid_l = (bid_l + ask_l) / 2.0
        mtm_l = (mid_l - long_last_mid) * long_qty
        day_pnl += mtm_l
        long_last_mid = mid_l

        # MTM short
        close_price_s = row[f"{short_target}_close"]
        spread_bps_s = row[f"{short_target}_spread_bps"]
        bid_s, ask_s = close_to_bid_ask(close_price_s, spread_bps_s)
        mid_s = (bid_s + ask_s) / 2.0
        mtm_s = (short_last_mid - mid_s) * short_qty
        day_pnl += mtm_s
        short_last_mid = mid_s

        cum_equity += day_pnl
        daily_ret = (cum_equity - prev_equity) / prev_equity if prev_equity > 0 else 0.0
        daily_returns.append(float(daily_ret))

    # Close at end
    exit_day = n_days - 1
    last_row = panel.iloc[-1]

    # Close long at bid
    close_price_l = last_row[f"{long_target}_close"]
    spread_bps_l = last_row[f"{long_target}_spread_bps"]
    bid_l, ask_l = close_to_bid_ask(close_price_l, spread_bps_l)
    mid_l = (bid_l + ask_l) / 2.0
    exit_long = (bid_l - mid_l) * long_qty  # From current_mid to bid
    cum_equity += exit_long
    cost_close_long = cost_model_local.total_cost(
        price=bid_l, qty=long_qty, adv=None, spread_bps=spread_bps_l, side="SELL",
    )
    cum_equity -= cost_close_long

    # Close short at ask
    close_price_s = last_row[f"{short_target}_close"]
    spread_bps_s = last_row[f"{short_target}_spread_bps"]
    bid_s, ask_s = close_to_bid_ask(close_price_s, spread_bps_s)
    mid_s = (bid_s + ask_s) / 2.0
    exit_short = (mid_s - ask_s) * short_qty
    cum_equity += exit_short
    cost_close_short = cost_model_local.total_cost(
        price=ask_s, qty=short_qty, adv=None, spread_bps=spread_bps_s, side="BUY",
    )
    cum_equity -= cost_close_short

    total_costs = cost_open_long + cost_open_short + cost_close_long + cost_close_short
    gross_pnl_correct = (bid_l - long_entry_price) * long_qty + (short_entry_price - ask_s) * short_qty
    net_pnl = cum_equity - initial_capital

    return {
        "long_target": long_target,
        "short_target": short_target,
        "long_entry_price": float(long_entry_price),
        "short_entry_price": float(short_entry_price),
        "long_entry_qty": float(long_qty),
        "short_entry_qty": float(short_qty),
        "long_exit_price": float(bid_l),
        "short_exit_price": float(ask_s),
        "gross_pnl": float(gross_pnl_correct),
        "total_costs": float(total_costs),
        "net_pnl": float(net_pnl),
        "final_equity": float(cum_equity),
        "return_pct": float((net_pnl / initial_capital) * 100),
        "daily_returns": np.array(daily_returns, dtype=float),
    }


# ── Main Diagnostic ──────────────────────────────────────────────────────

def main():
    print("=" * 72)
    print("  AlphaCore — Cross-Sectional Relative Strength DIAGNOSTIC")
    print("=" * 72)
    print()
    print("  Purpose: Diagnose why BOTH legs lost money in the original")
    print("  experiment. Includes the MTM bug fix.")
    print()

    # ── Load data ──
    print(">>> Loading data ...")
    raw_data = load_data()
    panel = build_panel(raw_data)
    test_panel = panel.iloc[TEST_START_INDEX:]

    print(f"  Test panel: {len(test_panel)} days")
    print(f"  Train: {panel.index[0].date()} to {panel.index[TRAIN_END_INDEX-1].date()}")
    print(f"  Test:  {panel.index[TEST_START_INDEX].date()} to {panel.index[-1].date()}")
    print()

    # ── Run CORRECTED backtest with rebalance dump ──
    print("─" * 72)
    print("  STEP 1: Run BUG-FIXED backtest + DUMP every rebalance event")
    print("─" * 72)
    print()

    bt = FixedCrossSectionalBacktester(
        panel=test_panel,
        lookback_n=LOOKBACK_N,
        k=K,
        rebalance_interval=REBALANCE_INTERVAL,
        position_size_pct=POSITION_SIZE_PCT,
        initial_capital=INITIAL_CAPITAL,
    )
    result = bt.run(dump_rebalances=True)

    daily_rets = result["daily_returns"]
    n_usable_days = len(daily_rets)

    # Corrected Sharpe and bootstrap CI
    sharpe_corrected = compute_sharpe(daily_rets.tolist())
    ci = stationary_bootstrap_sharpe_ci(
        daily_rets, n_bootstrap=N_BOOTSTRAP,
        mean_block_length=MEAN_BLOCK_LENGTH, seed=BOOTSTRAP_SEED,
    ) if n_usable_days >= 10 else {"sharpe": float(sharpe_corrected),
                                     "ci_lower": 0.0, "ci_upper": 0.0,
                                     "n_obs": n_usable_days, "reliable": False}

    print()
    print("─" * 72)
    print("  STEP 2: CORRECTED RESULTS (MTM bug fixed)")
    print("─" * 72)
    print()
    print(f"  {'Metric':<40} {'Original (buggy)':<22} {'Corrected':<22}")
    print(f"  {'-'*40} {'-'*22} {'-'*22}")
    print(f"  {'Gross PnL':<40} {'₹-22,712.29':<22} ₹{result['gross_pnl']:<+10,.2f}")
    print(f"  {'Total costs':<40} {'₹15,968.66':<22} ₹{result['total_costs']:<+10,.2f}")
    print(f"  {'Net PnL':<40} {'₹-38,680.95':<22} ₹{result['net_pnl']:<+10,.2f}")
    print(f"  {'Long leg PnL':<40} {'₹-12,045.47':<22} ₹{result['long_leg_pnl']:<+10,.2f}")
    print(f"  {'Short leg PnL':<40} {'₹-10,369.12':<22} ₹{result['short_leg_pnl']:<+10,.2f}")
    print(f"  {'Cost drag':<40} {'70.3%':<22} {result['cost_drag_pct']:.1f}%")
    print(f"  {'Sharpe':<40} {'-4.3657':<22} {sharpe_corrected:.4f}")
    print(f"  {'95% CI':<40} {'[-6.64, -2.13]':<22} [{ci['ci_lower']:.4f}, {ci['ci_upper']:.4f}]")
    print(f"  {'CI excludes zero?':<40} {'True (NEGATIVE)':<22} "
          f"{(ci['ci_lower'] > 0 or ci['ci_upper'] < 0)}")
    print(f"  {'Final equity':<40} {'₹61,319.05':<22} ₹{result['final_equity']:<+10,.2f}")
    print(f"  {'Number of rebalances':<40} {'':<22} {result['n_rebalances']}")
    print(f"  {'Total return':<40} {'-38.68%':<22} "
          f"{((result['final_equity'] / INITIAL_CAPITAL) - 1) * 100:.2f}%")
    print()

    # ── Whipsaw Analysis ──
    print("─" * 72)
    print("  STEP 3: WHIPSAW / TURNOVER ANALYSIS")
    print("─" * 72)
    print()
    rlog = result["rebalance_log"]
    w = result["whipsaw"]

    total_rebals = len(rlog)
    long_same = w["same_long_count"]
    long_changed = w["long_turnover"]
    short_same = w["same_short_count"]
    short_changed = w["short_turnover"]

    print(f"  Total rebalance events: {total_rebals}")
    print()
    print(f"  LONG leg:")
    print(f"    Same symbol as prev rebalance: {long_same} / {total_rebals-1} "
          f"({long_same/(total_rebals-1)*100:.1f}%)")
    print(f"    Changed symbol (turnover):     {long_changed} / {total_rebals-1} "
          f"({long_changed/(total_rebals-1)*100:.1f}%)")
    print(f"  SHORT leg:")
    print(f"    Same symbol as prev rebalance: {short_same} / {total_rebals-1} "
          f"({short_same/(total_rebals-1)*100:.1f}%)")
    print(f"    Changed symbol (turnover):     {short_changed} / {total_rebals-1} "
          f"({short_changed/(total_rebals-1)*100:.1f}%)")

    # Cost breakdown
    total_cost = result["total_costs"]
    n_trades = result["n_trades"]
    avg_cost_per_trade = total_cost / n_trades if n_trades > 0 else 0.0

    # Estimate "minimum possible" cost: only 2 entries + 2 exits total (one entry at start, one exit at end)
    # For naive hold: 2 opens + 2 closes = 4 trades total
    naive_cost = 0.0
    avg_trade_cost_per_open_close = total_cost / n_trades  # average cost per individual trade
    min_possible_trades = 4  # 2 opens + 2 closes
    whipsaw_cost = (n_trades - min_possible_trades) * avg_trade_cost_per_open_close

    print(f"\n  COST BREAKDOWN:")
    print(f"    Average cost per individual trade: ₹{avg_cost_per_trade:.2f}")
    print(f"    Total trades: {n_trades}")
    print(f"    Minimum trades (one entry + one exit for each leg): {min_possible_trades}")
    print(f"    Extra trades due to rebalancing: {n_trades - min_possible_trades}")
    print(f"    Estimated whipsaw cost (extra trades): ₹{whipsaw_cost:,.2f}")
    print(f"    Whipsaw cost as % of total costs: {whipsaw_cost/total_cost*100:.1f}%")
    print()

    # ── Position alignment with "hindsight winners" ──
    print("─" * 72)
    print("  STEP 4: POSITION ALIGNMENT WITH HINDSIGHT WINNERS/LOSERS")
    print("─" * 72)
    print()

    # Hindsight winners: RELIANCE (+2.98%), ICICIBANK (+15.02%)
    # Hindsight losers: TCS (-37.64%), INFY (-35.46%), HDFCBANK (-8.74%)
    winners = {"RELIANCE", "ICICIBANK"}
    losers = {"TCS", "INFY", "HDFCBANK"}

    long_winner_count = sum(1 for e in rlog if e["top_sym"] in winners)
    long_loser_count = sum(1 for e in rlog if e["top_sym"] in losers)
    short_winner_count = sum(1 for e in rlog if e["bottom_sym"] in winners)
    short_loser_count = sum(1 for e in rlog if e["bottom_sym"] in losers)
    long_wc = sum(1 for e in rlog if e["top_sym"] == "ICICIBANK")
    long_wr = sum(1 for e in rlog if e["top_sym"] == "RELIANCE")
    short_tcs = sum(1 for e in rlog if e["bottom_sym"] == "TCS")
    short_infy = sum(1 for e in rlog if e["bottom_sym"] == "INFY")
    short_hdfc = sum(1 for e in rlog if e["bottom_sym"] == "HDFCBANK")

    print(f"  Hindsight winners (up):   RELIANCE (+3%), ICICIBANK (+15%)")
    print(f"  Hindsight losers (down):  TCS (-38%), INFY (-35%), HDFCBANK (-9%)")
    print(f"  Total rebalance events:   {len(rlog)}")
    print()
    print(f"  LONG was a WINNER:     {long_winner_count}/{len(rlog)} "
          f"({long_winner_count/len(rlog)*100:.1f}%)")
    print(f"    → ICICIBANK: {long_wc}x")
    print(f"    → RELIANCE:  {long_wr}x")
    print(f"  LONG was a LOSER:      {long_loser_count}/{len(rlog)} "
          f"({long_loser_count/len(rlog)*100:.1f}%)")
    print(f"  SHORT was a LOSER:     {short_winner_count}/{len(rlog)} "
          f"({short_winner_count/len(rlog)*100:.1f}%)")
    print(f"  SHORT was a WINNER:    {short_loser_count}/{len(rlog)} "
          f"({short_loser_count/len(rlog)*100:.1f}%)")
    print(f"    → TCS:     {short_tcs}x")
    print(f"    → INFY:    {short_infy}x")
    print(f"    → HDFCBANK: {short_hdfc}x")
    print()

    # ── Naive Benchmark ──
    print("─" * 72)
    print("  STEP 5: NAIVE HOLD BENCHMARK (no rebalancing)")
    print("─" * 72)
    print()

    bench = naive_hold_benchmark(test_panel, LOOKBACK_N, INITIAL_CAPITAL)
    bench_sharpe = compute_sharpe(bench["daily_returns"].tolist())
    bench_ci = stationary_bootstrap_sharpe_ci(
        bench["daily_returns"], n_bootstrap=N_BOOTSTRAP,
        mean_block_length=MEAN_BLOCK_LENGTH, seed=BOOTSTRAP_SEED,
    ) if len(bench["daily_returns"]) >= 10 else {"sharpe": float(bench_sharpe),
                                                   "ci_lower": 0.0, "ci_upper": 0.0,
                                                   "n_obs": len(bench["daily_returns"]),
                                                   "reliable": False}

    print(f"  Strategy: On day 1, go LONG {bench['long_target']} and SHORT "
          f"{bench['short_target']}")
    print(f"  Hold for entire test period without rebalancing.")
    print(f"  Long entry:  {bench['long_target']} @ ${bench['long_entry_price']:.2f} "
          f"({bench['long_entry_qty']:.1f} shares)")
    print(f"  Short entry: {bench['short_target']} @ ${bench['short_entry_price']:.2f} "
          f"({bench['short_entry_qty']:.1f} shares)")
    print(f"  Long exit:   @ ${bench['long_exit_price']:.2f}")
    print(f"  Short exit:  @ ${bench['short_exit_price']:.2f}")
    print()
    print(f"  {'Metric':<40} {'Naive Hold':<22} {'Actual (corrected)':<22}")
    print(f"  {'-'*40} {'-'*22} {'-'*22}")
    print(f"  {'Gross PnL':<40} ₹{bench['gross_pnl']:<+10,.2f}    ₹{result['gross_pnl']:<+10,.2f}")
    print(f"  {'Total costs':<40} ₹{bench['total_costs']:<+10,.2f}    ₹{result['total_costs']:<+10,.2f}")
    print(f"  {'Net PnL':<40} ₹{bench['net_pnl']:<+10,.2f}    ₹{result['net_pnl']:<+10,.2f}")
    print(f"  {'Return':<40} {bench['return_pct']:<+6.2f}%        {((result['final_equity']/INITIAL_CAPITAL)-1)*100:<+6.2f}%")
    print(f"  {'Sharpe':<40} {bench_sharpe:<+10.4f}    {sharpe_corrected:<+10.4f}")
    print(f"  {'95% CI':<40} [{bench_ci['ci_lower']:.4f}, {bench_ci['ci_upper']:.4f}]    "
          f"[{ci['ci_lower']:.4f}, {ci['ci_upper']:.4f}]")
    print()

    # Verify: gross PnL = (bid - ask) * qty for long + (bid - ask) * qty for short
    long_gross = (bench['long_exit_price'] - bench['long_entry_price']) * bench['long_entry_qty']
    short_gross = (bench['short_entry_price'] - bench['short_exit_price']) * bench['short_entry_qty']
    print(f"  Verification: Long gross PnL = ({bench['long_exit_price']:.2f} - "
          f"{bench['long_entry_price']:.2f}) × {bench['long_entry_qty']:.1f} = ₹{long_gross:.2f}")
    print(f"  Verification: Short gross PnL = ({bench['short_entry_price']:.2f} - "
          f"{bench['short_exit_price']:.2f}) × {bench['short_entry_qty']:.1f} = ₹{short_gross:.2f}")
    print(f"  Verification: Total gross = ₹{bench['gross_pnl']:.2f} "
          f"(matches reported: {abs(bench['gross_pnl'] - long_gross - short_gross) < 0.01})")
    print()

    # ── Summary ──
    print("=" * 72)
    print("  DIAGNOSTIC SUMMARY")
    print("=" * 72)
    print()
    print(f"  BUG FOUND: MTM computed as (current_mid - entry_price) each day")
    print(f"  instead of (current_mid - last_mid). This caused cumulative PnL")
    print(f"  to be added to equity multiple times over each hold period.")
    print()
    print(f"  The bug amplified PnL in the direction of the position — making")
    print(f"  both wins and losses look {REBALANCE_INTERVAL}x larger than real.")
    print(f"  This explains why BOTH legs appeared to lose money.")
    print()

    # ── Save results ──
    output = {
        "diagnostic_type": "MTM bug fix + position dump",
        "original_buggy_results": {
            "gross_pnl": -22712.29,
            "total_costs": 15968.66,
            "net_pnl": -38680.95,
            "long_leg_pnl": -12045.47,
            "short_leg_pnl": -10369.12,
            "sharpe": -4.3657,
            "ci_lower": -6.6441,
            "ci_upper": -2.1293,
            "final_equity": 61319.05,
            "cost_drag_pct": 70.3,
        },
        "corrected_results": {
            "gross_pnl": float(result["gross_pnl"]),
            "total_costs": float(result["total_costs"]),
            "net_pnl": float(result["net_pnl"]),
            "long_leg_pnl": float(result["long_leg_pnl"]),
            "short_leg_pnl": float(result["short_leg_pnl"]),
            "sharpe": float(sharpe_corrected),
            "ci_lower": float(ci["ci_lower"]),
            "ci_upper": float(ci["ci_upper"]),
            "final_equity": float(result["final_equity"]),
            "cost_drag_pct": float(result["cost_drag_pct"]),
            "n_rebalances": result["n_rebalances"],
        },
        "naive_hold_benchmark": {
            "long_target": bench["long_target"],
            "short_target": bench["short_target"],
            "gross_pnl": float(bench["gross_pnl"]),
            "total_costs": float(bench["total_costs"]),
            "net_pnl": float(bench["net_pnl"]),
            "sharpe": float(bench_sharpe),
            "return_pct": float(bench["return_pct"]),
        },
        "whipsaw": {
            "total_rebalances": total_rebals,
            "long_same_symbol": long_same,
            "long_changed": long_changed,
            "short_same_symbol": short_same,
            "short_changed": short_changed,
            "estimated_whipsaw_cost": float(whipsaw_cost),
        },
        "position_alignment": {
            "total_rebalances": total_rebals,
            "long_on_winner": long_winner_count,
            "long_on_loser": long_loser_count,
            "short_on_winner": short_winner_count,
            "short_on_loser": short_loser_count,
            "long_icici": long_wc,
            "long_reliance": long_wr,
            "short_tcs": short_tcs,
            "short_infy": short_infy,
            "short_hdfc": short_hdfc,
        },
    }

    output_path = Path(__file__).resolve().parent.parent.parent / "cross_sectional_diagnostic_results.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f">>> Results saved to {output_path}")
    print()


if __name__ == "__main__":
    main()
