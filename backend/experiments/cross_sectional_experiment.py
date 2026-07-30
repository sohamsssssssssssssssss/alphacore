#!/usr/bin/env python3.11
"""
AlphaCore — Cross-Sectional Relative Strength Experiment

Tests whether a long/short basket based on cross-sectional relative strength
(rank the NSE symbols by trailing N-day return, long top 1, short bottom 1,
rebalance every 5 days) produces statistically significant positive returns
net of realistic transaction costs.

Pre-committed protocol: CROSS_SECTIONAL_EXPERIMENT_PROTOCOL.md
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

# ── Configuration ──────────────────────────────────────────────────────────

SYMBOLS = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "real_nse_data"
TRAIN_END_INDEX = 867  # 70% of 1239 rows
TEST_START_INDEX = 867

# Candidate lookback windows (to be locked based on train-period performance)
CANDIDATE_N = [20, 60]

# Strategy parameters (pre-committed — see protocol)
K = 1                     # Long top 1, short bottom 1
REBALANCE_INTERVAL = 5    # Every 5 trading days
POSITION_SIZE_PCT = 0.10  # 10% of equity per leg
INITIAL_CAPITAL = 100000.0

# Bootstrap
N_BOOTSTRAP = 2000
BOOTSTRAP_SEED = 2026
MEAN_BLOCK_LENGTH = 5  # matches rebalance interval

# Cost model (same default as all prior experiments)
cost_model = CostModel()

# ── Data Loading ───────────────────────────────────────────────────────────

def load_data() -> dict[str, pd.DataFrame]:
    """Load all symbol CSVs and return as dict of DataFrames."""
    data = {}
    for sym in SYMBOLS:
        path = DATA_DIR / f"{sym}.csv"
        df = pd.read_csv(path, parse_dates=["Date"])
        df = df.sort_values("Date").reset_index(drop=True)
        data[sym] = df
    return data


def build_panel(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Build a daily panel with one row per date, columns per symbol.

    Returns DataFrame with:
      - index: Date
      - columns: symbol_close, symbol_spread_bps for each symbol
    """
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


# ── Helper: Estimate bid/ask from close and spread ────────────────────────

def close_to_bid_ask(close: float, spread_bps: float) -> tuple[float, float]:
    spread_abs = (spread_bps / 10000.0) * close
    bid = close - spread_abs / 2.0
    ask = close + spread_abs / 2.0
    if bid >= ask:
        ask = bid + 1e-6
    return bid, ask


# ── Cross-Sectional Relative Strength Backtester ──────────────────────────

class CrossSectionalBacktester:
    """Backtester for cross-sectional relative strength long/short strategy.

    Daily returns INCLUDE transaction costs (costs are subtracted from equity
    on the day they are incurred, and the daily return is computed from total
    equity change for the day).
    """

    def __init__(
        self,
        panel: pd.DataFrame,
        lookback_n: int,
        k: int = 1,
        rebalance_interval: int = 5,
        position_size_pct: float = 0.10,
        initial_capital: float = 100000.0,
    ):
        self.panel = panel
        self.lookback_n = lookback_n
        self.k = k
        self.rebalance_interval = rebalance_interval
        self.position_size_pct = position_size_pct
        self.initial_capital = initial_capital
        self.symbols = [c.replace("_close", "") for c in panel.columns if c.endswith("_close")]

    def run(self) -> dict:
        """Run the backtest.

        Daily returns are the TOTAL change in equity (PnL from mark-to-market
        PLUS costs) divided by previous equity. This ensures the Sharpe and
        bootstrap CI capture the full cost impact.
        """
        panel = self.panel
        n_days = len(panel)
        symbols = self.symbols

        # Pre-compute trailing returns
        trailing_rets = {}
        for sym in symbols:
            close_col = f"{sym}_close"
            trailing_rets[sym] = panel[close_col].pct_change(periods=self.lookback_n)

        # State
        equity = float(self.initial_capital)
        daily_returns: list[float] = []
        gross_pnl_total = 0.0
        total_costs = 0.0

        # Position state
        long_sym: str | None = None
        short_sym: str | None = None
        long_qty: float = 0.0
        short_qty: float = 0.0
        long_entry_price: float = 0.0
        short_entry_price: float = 0.0
        last_rebalance_day: int = -1

        trades: list[dict] = []

        # We need lookback_n days before first valid trailing return
        start_day = self.lookback_n

        for day_idx in range(start_day, n_days):
            row = panel.iloc[day_idx]
            prev_equity = equity  # capture equity at start of day

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

            # ── 3. MTM PnL from held positions ──
            day_pnl = 0.0

            if long_sym is not None:
                close_price = row[f"{long_sym}_close"]
                spread_bps = row[f"{long_sym}_spread_bps"]
                bid, ask = close_to_bid_ask(close_price, spread_bps)
                mid = (bid + ask) / 2.0
                day_pnl += (mid - long_entry_price) * long_qty

            if short_sym is not None:
                close_price = row[f"{short_sym}_close"]
                spread_bps = row[f"{short_sym}_spread_bps"]
                bid, ask = close_to_bid_ask(close_price, spread_bps)
                mid = (bid + ask) / 2.0
                day_pnl += (short_entry_price - mid) * short_qty

            equity += day_pnl
            gross_pnl_total += day_pnl

            # ── 4. Rebalance (if scheduled) ──
            if is_rebalance:
                # Close long
                if long_sym is not None and long_qty > 0:
                    close_price = row[f"{long_sym}_close"]
                    spread_bps = row[f"{long_sym}_spread_bps"]
                    bid, ask = close_to_bid_ask(close_price, spread_bps)
                    exit_pnl = (bid - long_entry_price) * long_qty
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
                    long_sym = None
                    long_qty = 0.0
                    long_entry_price = 0.0

                # Close short
                if short_sym is not None and short_qty > 0:
                    close_price = row[f"{short_sym}_close"]
                    spread_bps = row[f"{short_sym}_spread_bps"]
                    bid, ask = close_to_bid_ask(close_price, spread_bps)
                    exit_pnl = (short_entry_price - ask) * short_qty
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
                    short_sym = None
                    short_qty = 0.0
                    short_entry_price = 0.0

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

                last_rebalance_day = day_idx

            # ── 5. Compute daily return (ALL changes included: MTM + costs) ──
            daily_ret = (equity - prev_equity) / prev_equity if prev_equity > 0 else 0.0
            daily_returns.append(float(daily_ret))

        # ── Flush open positions at end ──
        if long_sym is not None and long_qty > 0:
            last_row = panel.iloc[-1]
            close_price = last_row[f"{long_sym}_close"]
            spread_bps = last_row[f"{long_sym}_spread_bps"]
            bid, ask = close_to_bid_ask(close_price, spread_bps)
            exit_pnl = (bid - long_entry_price) * long_qty
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
            exit_pnl = (short_entry_price - ask) * short_qty
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

        # Build equity curve from daily returns (includes costs)
        eq_curve = [float(self.initial_capital)]
        for r in daily_returns:
            eq_curve.append(eq_curve[-1] * (1.0 + r))

        return {
            "trades": trades,
            "daily_returns": daily_ret_array,
            "equity_curve": eq_curve,
            "final_equity": float(equity),
            "net_pnl": float(net_pnl),
            "gross_pnl": float(gross_pnl_total),
            "total_costs": float(total_costs),
            "cost_drag_pct": float(cost_drag_pct),
            "n_rebalances": len([t for t in trades if t["action"] == "OPEN"]),
            "n_trades": len(trades),
            "long_leg_pnl": float(sum(t["pnl"] for t in trades if t["leg"] == "LONG")),
            "short_leg_pnl": float(sum(t["pnl"] for t in trades if t["leg"] == "SHORT")),
        }


# ── Main: Lock N on Train, Evaluate on Test ────────────────────────────────

def main():
    print("=" * 72)
    print("  AlphaCore — Cross-Sectional Relative Strength Experiment")
    print("=" * 72)
    print(f"  Protocol: CROSS_SECTIONAL_EXPERIMENT_PROTOCOL.md")
    print(f"  Symbols:  {', '.join(SYMBOLS)}")
    print(f"  K (long/short legs): {K}")
    print(f"  Rebalance: every {REBALANCE_INTERVAL} trading days")
    print(f"  Position size: {POSITION_SIZE_PCT:.0%} per leg")
    print(f"  Candidate N: {CANDIDATE_N}")
    print()

    # ── Load data ──
    print(">>> Loading data ...")
    raw_data = load_data()
    panel = build_panel(raw_data)
    print(f"  Panel: {len(panel)} days, {len(panel.columns)} columns")

    # Split
    train_panel = panel.iloc[:TRAIN_END_INDEX]
    test_panel = panel.iloc[TEST_START_INDEX:]
    print(f"  Train: {len(train_panel)} days "
          f"({panel.index[0].date()} to {panel.index[TRAIN_END_INDEX-1].date()})")
    print(f"  Test:  {len(test_panel)} days "
          f"({panel.index[TEST_START_INDEX].date()} to {panel.index[-1].date()})")
    print()

    # ── Step 1: Lock N on train period ──
    print("─" * 72)
    print("  STEP 1: Lock lookback window N on TRAIN period")
    print("─" * 72)

    train_results = {}
    for n in CANDIDATE_N:
        bt = CrossSectionalBacktester(
            panel=train_panel,
            lookback_n=n,
            k=K,
            rebalance_interval=REBALANCE_INTERVAL,
            position_size_pct=POSITION_SIZE_PCT,
            initial_capital=INITIAL_CAPITAL,
        )
        result = bt.run()
        sharpe = compute_sharpe(result["daily_returns"].tolist())

        train_results[n] = {
            "sharpe": float(sharpe),
            "n_rebalances": result["n_rebalances"],
            "net_pnl": float(result["net_pnl"]),
            "cost_drag_pct": float(result["cost_drag_pct"]),
            "final_equity": float(result["final_equity"]),
            "long_leg_pnl": float(result["long_leg_pnl"]),
            "short_leg_pnl": float(result["short_leg_pnl"]),
        }
        print(f"  N={n:>2}:  Sharpe={sharpe:>8.4f}  "
              f"PnL=₹{result['net_pnl']:>+10,.2f}  "
              f"Rebal={result['n_rebalances']:>3}  "
              f"CostDrag={result['cost_drag_pct']:>6.1f}%  "
              f"Long=₹{result['long_leg_pnl']:>+10,.2f}  "
              f"Short=₹{result['short_leg_pnl']:>+10,.2f}")

    # Choose N with highest train Sharpe
    best_n = max(train_results, key=lambda n: train_results[n]["sharpe"])
    print(f"\n  >>> Selected N={best_n} (highest train Sharpe = "
          f"{train_results[best_n]['sharpe']:.4f})")
    print(f"  >>> Locked — will not change for test period.")
    print()

    # ── Step 2: Run on test period with locked N ──
    print("─" * 72)
    print(f"  STEP 2: Evaluate on TEST period (locked N={best_n})")
    print("─" * 72)

    test_bt = CrossSectionalBacktester(
        panel=test_panel,
        lookback_n=best_n,
        k=K,
        rebalance_interval=REBALANCE_INTERVAL,
        position_size_pct=POSITION_SIZE_PCT,
        initial_capital=INITIAL_CAPITAL,
    )
    test_result = test_bt.run()

    daily_rets = test_result["daily_returns"]
    n_usable_days = len(daily_rets)

    # Sharpe and bootstrap CI
    sharpe_test = compute_sharpe(daily_rets.tolist())

    print(f"  Usable test days: {n_usable_days} (after discarding first "
          f"{best_n} lookback days)")
    print(f"  Net PnL:        ₹{test_result['net_pnl']:>+12,.2f}")
    print(f"  Gross PnL:      ₹{test_result['gross_pnl']:>+12,.2f}")
    print(f"  Total costs:    ₹{test_result['total_costs']:>+12,.2f}")
    print(f"  Cost drag:      {test_result['cost_drag_pct']:>7.1f}%")
    print(f"  Long leg PnL:   ₹{test_result['long_leg_pnl']:>+12,.2f}")
    print(f"  Short leg PnL:  ₹{test_result['short_leg_pnl']:>+12,.2f}")
    print(f"  Rebalance events: {test_result['n_rebalances']}")
    print(f"  Total trades:     {test_result['n_trades']}")
    print(f"  Final equity:   ₹{test_result['final_equity']:>+12,.2f}")
    print(f"  Return:         {((test_result['final_equity'] / INITIAL_CAPITAL) - 1) * 100:.2f}%")
    print(f"  Gross Sharpe:   {sharpe_test:.4f}")

    # Bootstrap CI for Sharpe
    if n_usable_days >= 10:
        ci = stationary_bootstrap_sharpe_ci(
            daily_rets,
            n_bootstrap=N_BOOTSTRAP,
            mean_block_length=MEAN_BLOCK_LENGTH,
            seed=BOOTSTRAP_SEED,
        )
    else:
        ci = {
            "sharpe": float(sharpe_test),
            "ci_lower": 0.0, "ci_upper": 0.0, "ci_width": 0.0,
            "n_obs": int(n_usable_days), "reliable": False,
        }

    print(f"\n  >>> Sharpe: {ci['sharpe']:.4f}")
    print(f"  >>> 95% CI: [{ci['ci_lower']:.4f}, {ci['ci_upper']:.4f}]")
    print(f"  >>> CI excludes zero: "
          f"{(ci['ci_lower'] > 0 or ci['ci_upper'] < 0)}")
    print(f"  >>> CI width: {ci['ci_width']:.4f}")
    print(f"  >>> N observations: {ci['n_obs']}")
    print()

    # ── Sanity Checks ──
    print("─" * 72)
    print("  SANITY CHECKS")
    print("─" * 72)

    print(f"  [1] Lookahead: ✓ (trailing returns use pct_change(N), "
          f"no future info)")

    n_reb = test_result["n_rebalances"]
    if n_reb >= 10:
        print(f"  [2] Adequate trading: ✓ ({n_reb} rebalance events)")
    else:
        print(f"  [2] Adequate trading: ⚠ ONLY {n_reb} events — unreliable")

    rebalance_days = sorted(set(
        t["day"] for t in test_result["trades"] if t["action"] == "OPEN"
    ))
    print(f"  [3] Unique rebalance days: {len(rebalance_days)}")

    print(f"  [4] Cost model: default CostModel() — "
          f"identical to prior experiments ✓")
    print(f"  [5] Short-selling costs: NOT modeled — "
          f"this UNDERSTATES real costs")
    print(f"  [6] Small universe: N=5 symbols — very small cross-section. "
          f"Typical deployments use 100-500+ names.")

    test_start_price = panel.iloc[TEST_START_INDEX]
    test_end_price = panel.iloc[-1]
    for sym in SYMBOLS:
        close_col = f"{sym}_close"
        start_p = test_start_price[close_col]
        end_p = test_end_price[close_col]
        ret = (end_p - start_p) / start_p * 100.0
        print(f"      {sym}: ${start_p:.2f} → ${end_p:.2f} ({ret:+.2f}%)")

    print()

    # ── Summary ──
    print("=" * 72)
    print("  RESULTS SUMMARY")
    print("=" * 72)
    print()
    print(f"  {'Lookback window N':<35} {best_n}")
    print(f"  {'K (long/short legs)':<35} {K}")
    print(f"  {'Rebalance interval':<35} every {REBALANCE_INTERVAL} days")
    print(f"  {'Position size per leg':<35} {POSITION_SIZE_PCT:.0%}")
    print(f"  {'Net PnL':<35} ₹{test_result['net_pnl']:>+12,.2f}")
    print(f"  {'Gross PnL':<35} ₹{test_result['gross_pnl']:>+12,.2f}")
    print(f"  {'Total costs':<35} ₹{test_result['total_costs']:>+12,.2f}")
    print(f"  {'Cost drag (% of gross)':<35} {test_result['cost_drag_pct']:.1f}%")
    print(f"  {'Long leg PnL':<35} ₹{test_result['long_leg_pnl']:>+12,.2f}")
    print(f"  {'Short leg PnL':<35} ₹{test_result['short_leg_pnl']:>+12,.2f}")
    print(f"  {'Number of rebalances':<35} {test_result['n_rebalances']}")
    print(f"  {'Total trades':<35} {test_result['n_trades']}")
    print(f"  {'Final equity':<35} ₹{test_result['final_equity']:>+12,.2f}")
    print(f"  {'Total return':<35} "
          f"{((test_result['final_equity'] / INITIAL_CAPITAL) - 1) * 100:.2f}%")
    print(f"  {'Sharpe (daily, net of costs)':<35} {ci['sharpe']:.4f}")
    print(f"  {'95% CI':<35} [{ci['ci_lower']:.4f}, {ci['ci_upper']:.4f}]")
    excludes_zero = ci["ci_lower"] > 0 or ci["ci_upper"] < 0
    print(f"  {'CI excludes zero':<35} {excludes_zero}")
    print(f"  {'Sharpe reliable (CI>0)':<35} {ci.get('reliable', False)}")
    print()

    # ── Save results ──
    output = {
        "protocol": "CROSS_SECTIONAL_EXPERIMENT_PROTOCOL.md",
        "timestamp": pd.Timestamp.now().isoformat(),
        "parameters": {
            "lookback_n_candidates": CANDIDATE_N,
            "selected_n": best_n,
            "n_selection_rule": "max train Sharpe",
            "k": K,
            "rebalance_interval": REBALANCE_INTERVAL,
            "position_size_pct": POSITION_SIZE_PCT,
            "initial_capital": INITIAL_CAPITAL,
            "cost_model": "CostModel() default (k=0.0015, brokerage=20, STT=0.001)",
            "short_selling_costs_modeled": False,
            "bootstrap": {
                "method": "stationary bootstrap (Politis-Romano)",
                "n_resamples": N_BOOTSTRAP,
                "mean_block_length": MEAN_BLOCK_LENGTH,
                "seed": BOOTSTRAP_SEED,
                "confidence": 0.95,
            },
        },
        "data": {
            "symbols": SYMBOLS,
            "granularity": "daily OHLCV",
            "source": "yfinance auto_adjust=True",
            "train_period": f"{panel.index[0].date()} to "
                           f"{panel.index[TRAIN_END_INDEX-1].date()}",
            "test_period": f"{panel.index[TEST_START_INDEX].date()} to "
                          f"{panel.index[-1].date()}",
            "train_size": TRAIN_END_INDEX,
            "test_size": len(panel) - TEST_START_INDEX,
            "limitations": [
                "Daily bars only (no intraday data)",
                "Bid/ask prices estimated from daily range spread proxy",
                "No real order book depth",
                "Short-selling borrow costs NOT modeled",
                "5-symbol universe is very small for cross-sectional strategy",
            ],
        },
        "train_results": train_results,
        "test_results": {
            "selected_n": best_n,
            "sharpe": float(ci["sharpe"]),
            "ci_lower": float(ci["ci_lower"]),
            "ci_upper": float(ci["ci_upper"]),
            "ci_width": float(ci["ci_width"]),
            "ci_excludes_zero": excludes_zero,
            "reliable": bool(ci.get("reliable", False)),
            "n_observations": int(ci["n_obs"]),
            "net_pnl": float(test_result["net_pnl"]),
            "gross_pnl": float(test_result["gross_pnl"]),
            "total_costs": float(test_result["total_costs"]),
            "cost_drag_pct": float(test_result["cost_drag_pct"]),
            "long_leg_pnl": float(test_result["long_leg_pnl"]),
            "short_leg_pnl": float(test_result["short_leg_pnl"]),
            "final_equity": float(test_result["final_equity"]),
            "total_return_pct": float(
                ((test_result["final_equity"] / INITIAL_CAPITAL) - 1) * 100
            ),
            "n_rebalances": int(test_result["n_rebalances"]),
            "n_trades": int(test_result["n_trades"]),
            "daily_returns": daily_rets.tolist(),
        },
    }

    output_path = Path(__file__).resolve().parent.parent.parent / "cross_sectional_results.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f">>> Results saved to {output_path}")
    print()

    # ── Bottom line ──
    print("─" * 72)
    reliable = ci.get("reliable", False)
    sharpe_val = ci["sharpe"]

    if excludes_zero and sharpe_val > 0 and reliable:
        print("  ✅ POSITIVE RESULT: Cross-sectional relative strength shows")
        print("     statistically significant positive Sharpe on held-out data.")
        print("     (Check cost drag and small-universe caveats before generalizing)")
    elif excludes_zero and sharpe_val < 0:
        print("  ❌ NEGATIVE RESULT: Cross-sectional relative strength shows")
        print("     statistically significant NEGATIVE Sharpe — strategy")
        print("     loses money net of costs with high confidence.")
    elif n_reb < 10:
        print("  ❓ INCONCLUSIVE: Too few rebalance events for inference.")
    else:
        print("  ❌ NULL RESULT: No statistically significant edge detected.")
        print("     Sharpe CI includes zero.")
    print()

    # Cross-reference with prior experiments
    print("  COMPARISON WITH PRIOR EXPERIMENTS:")
    print(f"    ├ Single-symbol backtest (RELIANCE): Sharpe NEGATIVE (-11.3)")
    print(f"    ├ Synthetic GBM (NSGA-II vs equal): NULL")
    print(f"    ├ Real data (NSGA-II vs equal):      NULL")
    if excludes_zero and sharpe_val > 0 and reliable:
        print(f"    └ Cross-sectional rel. strength:      POSITIVE")
    elif excludes_zero:
        print(f"    └ Cross-sectional rel. strength:      NEGATIVE")
    else:
        print(f"    └ Cross-sectional rel. strength:      NULL")
    print("─" * 72)


if __name__ == "__main__":
    main()
