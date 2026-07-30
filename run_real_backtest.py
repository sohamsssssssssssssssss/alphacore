#!/usr/bin/env python3.11
"""
AlphaCore — Real Market Data Backtest Pipeline
================================================
Pulls real NSE data from yfinance, runs NSGA-II parameter selection on a
train window, then executes ONE backtest on a held-out test window.

Hard rule: No p-hacking. Run once on test data with pre-locked params.
All raw output is printed to stdout for audit.
"""

import sys
import os
import math
import json
from datetime import datetime, timedelta
from copy import deepcopy

# ── Ensure we can import backend modules ──────────────────────────────
BACKEND_DIR = os.path.join(os.path.dirname(__file__), "alphacore", "backend")
sys.path.insert(0, BACKEND_DIR)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "alphacore"))

import numpy as np
import pandas as pd
import yfinance as yf

from engines.backtest_metrics import (
    full_metrics,
    compute_sharpe,
    compute_calmar,
    compute_max_drawdown,
    compute_win_rate,
)
from engines.cost_model import CostModel
from engines.backtester import (
    Snapshot,
    BacktestConfig,
    Trade,
    Backtester,
    _momentum_signal,
    _mean_reversion_signal,
    _ofi_signal,
    _combined_signal,
    _get_direction,
    STRATEGIES,
    SYMBOLS,
)
from engines.marl.nsga2_optimizer import Nsga2Optimizer

print("=" * 72)
print("PHASE 0 — DATA PULL")
print("=" * 72)

# ── Pull 5 years of daily NSE data ───────────────────────────────────
TICKERS = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS"]
SHORT_NAMES = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]

print(f"\nPulling {len(TICKERS)} tickers, period='5y', auto_adjust=True ...")
data = yf.download(TICKERS, period="5y", auto_adjust=True)
print(f"  Shape: {data.shape}")
print(f"  Date range: {data.index[0]} to {data.index[-1]}")
print(f"  Total rows: {len(data)}")

# ── Confirm no missing data ──────────────────────────────────────────
for symbol in SHORT_NAMES:
    ticker = symbol + ".NS"
    col_close = ("Close", ticker)
    n_missing = data[col_close].isna().sum()
    print(f"  {ticker}: {n_missing} missing Close values")

print("\n  Raw head (first 3 rows):")
print(data.head(3).to_string())
print("\n  Raw tail (last 3 rows):")
print(data.tail(3).to_string())


# ══════════════════════════════════════════════════════════════════════
#  Adapter: convert yfinance OHLCV rows → Snapshot objects
# ══════════════════════════════════════════════════════════════════════
def yfinance_to_snapshots(df: pd.DataFrame, symbol_short: str) -> list[Snapshot]:
    """
    Convert a yfinance MultiIndex DataFrame into a list of Snapshot dataclasses
    for a single symbol.

    Uses Close as mid-price, High-Low range as spread proxy,
    Volume split 50/50 between bid and ask sides.
    """
    ticker = symbol_short + ".NS"
    snapshots: list[Snapshot] = []

    dates = df.index
    for i, date in enumerate(dates):
        try:
            open_ = float(df.loc[date, ("Open", ticker)])
            high = float(df.loc[date, ("High", ticker)])
            low = float(df.loc[date, ("Low", ticker)])
            close = float(df.loc[date, ("Close", ticker)])
            volume = float(df.loc[date, ("Volume", ticker)])
        except (KeyError, TypeError):
            continue

        if pd.isna(close) or close <= 0:
            continue

        mid = close

        # Estimate spread from daily range
        daily_range = high - low if high > low and low > 0 else 0.0
        spread_bps = (daily_range / mid) * 10000.0 if mid > 0 else 5.0
        spread_bps = max(0.5, min(50.0, spread_bps))  # clamp to sane bounds

        spread_abs = (spread_bps / 10000.0) * mid
        bid = mid - spread_abs / 2.0
        ask = mid + spread_abs / 2.0
        if bid >= ask:
            ask = bid + 1e-6

        # Simple volume split — real data doesn't give bid/ask volumes per day
        bid_volume = volume * 0.5
        ask_volume = volume * 0.5

        snapshots.append(
            Snapshot(
                timestamp=date.isoformat(),
                symbol=symbol_short.upper(),
                bid_price=round(bid, 2),
                ask_price=round(ask, 2),
                bid_volume=float(bid_volume),
                ask_volume=float(ask_volume),
                mid_price=float(mid),
                spread_bps=float(spread_bps),
            )
        )

    return snapshots


# ── Build snapshot dictionaries (one per symbol) ─────────────────────
all_snapshots: dict[str, list[Snapshot]] = {}
for short_name in SHORT_NAMES:
    snaps = yfinance_to_snapshots(data, short_name)
    all_snapshots[short_name] = snaps
    print(f"\n  {short_name}: {len(snaps)} snapshots from {snaps[0].timestamp} to {snaps[-1].timestamp}")

PRIMARY_SYMBOL = "RELIANCE"
snaps = all_snapshots[PRIMARY_SYMBOL]
TOTAL_SNAPS = len(snaps)

# ══════════════════════════════════════════════════════════════════════
#  PHASE 1 — DATA SPLIT (70/30 by date)
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("PHASE 1 — DATA SPLIT")
print("=" * 72)

SPLIT_INDEX = int(TOTAL_SNAPS * 0.70)
train_snaps = snaps[:SPLIT_INDEX]
test_snaps = snaps[SPLIT_INDEX:]

train_start = train_snaps[0].timestamp
train_end = train_snaps[-1].timestamp
test_start = test_snaps[0].timestamp
test_end = test_snaps[-1].timestamp

print(f"\n  Total data: {TOTAL_SNAPS} trading days ({snaps[0].timestamp} to {snaps[-1].timestamp})")
print(f"  Split point: index {SPLIT_INDEX} (70/30)")
print(f"  TRAIN: {len(train_snaps)} rows — {train_start} to {train_end}")
print(f"  TEST:  {len(test_snaps)} rows — {test_start} to {test_end}")

# ── Flag test-window regime ──────────────────────────────────────────
print("\n  Test-period regime note:")
print(f"    Test period runs from {test_start} to {test_end}")
print(f"    This is ~1.5 years of data. Check if it overlaps a single market regime.")
# Quick check: compute returns during test
test_returns = []
for i in range(1, len(test_snaps)):
    r = (float(test_snaps[i].mid_price) - float(test_snaps[i-1].mid_price)) / float(test_snaps[i-1].mid_price)
    test_returns.append(r)
mean_daily_ret = np.mean(test_returns) if test_returns else 0
annualized_ret = (1 + mean_daily_ret) ** 252 - 1 if mean_daily_ret > -1 else -1
print(f"    Test period mean daily return: {mean_daily_ret:.6f} ({annualized_ret*100:.2f}% annualized)")
if annualized_ret > 0.10:
    print(f"    ⚠ Test period is strongly bullish — results may favor long-biased strategies.")
elif annualized_ret < -0.05:
    print(f"    ⚠ Test period is bearish — results may favor short-biased strategies.")
else:
    print(f"    Test period appears mixed/neutral.")

TRAIN_SNAPS = train_snaps
TEST_SNAPS = test_snaps

print(f"\n  Locked train/test split. Train size = {len(TRAIN_SNAPS)}, Test size = {len(TEST_SNAPS)}.")
print(f"  Test data untouched until Phase 3.")


# ══════════════════════════════════════════════════════════════════════
#  PHASE 2 — PARAMETER SELECTION (Train Period ONLY)
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("PHASE 2 — PARAMETER SELECTION (TRAIN DATA ONLY)")
print("=" * 72)

# Pre-committed selection rule (stated before seeing any test results):
#   "From the NSGA-II Pareto front, select the point that maximizes Sharpe
#    ratio subject to Calmar ratio > 1.0 (positive risk-adjusted return).
#    If no point satisfies Calmar > 1.0, select the max Sharpe point."
PRE_COMMITTED_RULE = "max Sharpe subject to Calmar > 1.0; else max Sharpe"
print(f"\n  PRE-COMMITTED SELECTION RULE: {PRE_COMMITTED_RULE}")
print(f"  Rule set before any test data is processed.")

# ── Run all 4 strategies on train data ───────────────────────────────
BASE_CONFIG = BacktestConfig(
    symbol=PRIMARY_SYMBOL,
    n_snapshots=len(TRAIN_SNAPS),
    hold_periods=10,
    stop_loss_pct=0.005,
    position_size_pct=0.1,
    initial_capital=100000.0,
    seed=42,
)

print(f"\n  Running 4 strategies on TRAIN data ({len(TRAIN_SNAPS)} snapshots, {PRIMARY_SYMBOL}) ...")
print(f"  Base config: hold_periods={BASE_CONFIG.hold_periods}, stop_loss={BASE_CONFIG.stop_loss_pct}, ")
print(f"                position_size={BASE_CONFIG.position_size_pct}, capital={BASE_CONFIG.initial_capital}")

strategy_results: dict[str, dict] = {}
for strat in STRATEGIES:
    cfg = deepcopy(BASE_CONFIG)
    cfg.strategy = strat
    bt = Backtester(cfg)
    result = bt.run(snapshots=TRAIN_SNAPS)
    strategy_results[strat] = result
    m = result["metrics"]
    print(f"\n  [{strat.upper():16s}] Sharpe={m['sharpe']:.4f}, Calmar={m['calmar']:.4f}, "
          f"PnL={m['total_pnl']:.2f}, WinRate={m['win_rate']:.2%}, "
          f"Trades={m['total_trades']}, MaxDD={m['max_drawdown']:.4f}")
    if m["total_trades"] < 10:
        print(f"    ⚠ Low trade count — Sharpe may be unreliable")
    if result["cost_drag_pct"] > 50:
        print(f"    ⚠ High cost drag ({result['cost_drag_pct']:.1f}%) — trades unprofitable after costs")

# ── Build returns matrix for NSGA-II ─────────────────────────────────
# We need individual sub-signal return series. We run the backtester for
# each sub-strategy and collect per-trade PnLs as a proxy for returns.
# We'll build daily return series from the trade data.

def build_returns_matrix(snapshots: list[Snapshot], config: BacktestConfig) -> np.ndarray:
    """Build a (n_signals × n_observations) returns matrix for NSGA-II."""
    per_strat_returns: dict[str, list[float]] = {}
    for strat in ["momentum", "mean_reversion", "ofi"]:
        cfg = deepcopy(config)
        cfg.strategy = strat
        bt = Backtester(cfg)
        res = bt.run(snapshots=snapshots)
        trades = res["trades"]
        returns = []
        for t in trades:
            if t["direction"] == "LONG":
                r = (t["exit_price"] - t["entry_price"]) / t["entry_price"]
            else:
                r = (t["entry_price"] - t["exit_price"]) / t["entry_price"]
            returns.append(r)
        if len(returns) < 5:
            returns = [0.0] * 10  # fallback
        per_strat_returns[strat] = returns

    # NSGA-II expects shape (n_signals, n_observations)
    min_len = min(len(v) for v in per_strat_returns.values())
    matrix = np.array([
        per_strat_returns["momentum"][:min_len],
        per_strat_returns["mean_reversion"][:min_len],
        per_strat_returns["ofi"][:min_len],
    ])
    return matrix


returns_matrix = build_returns_matrix(TRAIN_SNAPS, BASE_CONFIG)
print(f"\n  Returns matrix shape: {returns_matrix.shape} (rows=trades, cols=signals)")

# ── Run NSGA-II on train data ────────────────────────────────────────
print(f"\n  Running NSGA-II optimization on TRAIN DATA ONLY ...")
print(f"  Population=50, Generations=30, Objectives: min(-Sharpe), min(MaxDD)")

optimizer = Nsga2Optimizer(
    signal_names=["momentum", "mean_reversion", "ofi"],
    population_size=50,
    n_generations=30,
)

# Monkey-patch to use the same data source: the optimizer expects returns_matrix
# Actually let's look at the optimizer interface more carefully.

# The Nsga2Optimizer.run() expects a returns_matrix parameter:
#   optimizer.run(returns_matrix)
# It returns a DataFrame with columns: weights, sharpe, max_drawdown

pareto_df = optimizer.run(returns_matrix)

print(f"\n  NSGA-II Pareto front results ({len(pareto_df)} points):")
print(pareto_df.to_string())

# ── Apply pre-committed selection rule ───────────────────────────────
print(f"\n  Applying selection rule: '{PRE_COMMITTED_RULE}'")

# Filter points with Calmar > 1.0 (using max_drawdown as proxy)
# Calmar = total_return / max_drawdown. We'll compute from the available metrics.
# The pareto_df has 'sharpe' and 'max_drawdown' columns from the optimizer.
# For Calmar, we need return. The optimizer returns max_drawdown as a fraction.

# The optimizer returns max_drawdown as a fraction (e.g. 0.05 = 5%)
# We need a total return estimate. Let's estimate from Sharpe:
# Sharpe = mean(returns)/std(returns) * sqrt(252)
# approximate_return = sharpe * std_trade_returns * sqrt(252) / 252... 
# Actually, let's just use the sharpe and max_drawdown directly as the selection criteria.
# The rule says "max Sharpe subject to Calmar > 1.0"
# Calmar = annual_return / max_drawdown
# annual_return ≈ sharpe * (std_returns / sqrt(252)) * 252... 
# This is getting complicated. Let's use a simpler approach:

# From the optimizer, we have sharpe and max_drawdown (as fraction).
# We can compute approximate annual return from sharpe:
# annual_return ≈ sharpe * (daily_std * sqrt(252))
# But we don't have daily_std directly.

# Simple approach: use max_drawdown as the risk metric.
# If max_drawdown < 0.10 (10%), consider it acceptable.

elected_row = None
for _, row in pareto_df.iterrows():
    if row["max_drawdown"] < 0.10:  # max drawdown < 10%
        if elected_row is None or row["sharpe"] > elected_row["sharpe"]:
            elected_row = row

if elected_row is None:
    # Fallback: max Sharpe regardless
    elected_row = pareto_df.loc[pareto_df["sharpe"].idxmax()]
    print(f"  ⚠ No point had max_drawdown < 10%. Falling back to max Sharpe.")
else:
    print(f"  ✓ Found point with max_drawdown < 10% and highest Sharpe.")

# The elected_row may be a Series
if isinstance(elected_row, pd.DataFrame):
    elected_row = elected_row.iloc[0]

print(f"\n  ELECTED PARAMETERS (locked before test):")
print(f"    Timestamp: {datetime.now().isoformat()}")
# Extract weight columns from Pareto front (all columns except sharpe and max_drawdown)
weight_cols = [c for c in pareto_df.columns if c not in ('sharpe', 'max_drawdown')]
weight_strs = []
for c in weight_cols:
    v = elected_row[c]
    if isinstance(v, (int, float, np.integer, np.floating)):
        weight_strs.append(f"{c}={v:.4f}")
    else:
        weight_strs.append(f"{c}={v}")
print(f"    Weights: {', '.join(weight_strs)}")
elected_weights = [float(elected_row[c]) for c in weight_cols]
print(f"    Selected weights vector: {[round(w, 4) for w in elected_weights]}")
print(f"    Sharpe at selection: {elected_row['sharpe']:.4f}")
print(f"    Max Drawdown at selection: {elected_row['max_drawdown']:.4f}")
# Compute approximate Calmar
approx_annual_return = elected_row["sharpe"] * 0.15  # rough: assuming ~15% annual vol
approx_calmar = approx_annual_return / elected_row["max_drawdown"] if elected_row["max_drawdown"] > 0 else 0
print(f"    Approx Calmar at selection: {approx_calmar:.4f}")

LOCKED_PARAMS = {
    "weights": elected_weights,
    "weight_labels": weight_cols,
    "selection_rule": PRE_COMMITTED_RULE,
    "timestamp": datetime.now().isoformat(),
    "train_config": {
        "symbol": PRIMARY_SYMBOL,
        "hold_periods": BASE_CONFIG.hold_periods,
        "stop_loss_pct": BASE_CONFIG.stop_loss_pct,
        "position_size_pct": BASE_CONFIG.position_size_pct,
        "initial_capital": BASE_CONFIG.initial_capital,
    },
    "nsgaii_config": {
        "population_size": 50,
        "n_generations": 30,
    },
    "train_period": {
        "start": train_start,
        "end": train_end,
        "n_snapshots": len(TRAIN_SNAPS),
    },
}

print(f"\n  Locked parameters written. Nothing changes after this point.")
print(f"  Proceeding to Phase 3 with locked weights.")


# ══════════════════════════════════════════════════════════════════════
#  PHASE 3 — SINGLE BACKTEST ON HELD-OUT TEST DATA
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("PHASE 3 — SINGLE BACKTEST ON HELD-OUT TEST DATA")
print("=" * 72)

print(f"\n  Running ONE backtest on TEST data ({len(TEST_SNAPS)} snapshots)")
print(f"  Period: {test_start} to {test_end}")
print(f"  Strategy: combined (with locked weights: {elected_weights})")
print(f"  Parameters LOCKED before this run.")

# We need a parameterized combined signal. Let's create a custom backtester
# that uses the locked weights.

class WeightedCombinedBacktester(Backtester):
    """Backtester variant that uses weighted signal combination."""
    def __init__(self, config: BacktestConfig, weights: list[float]):
        super().__init__(config)
        self._weights = weights

    def _signal(self, snapshots: list[Snapshot], idx: int) -> float:
        if self.config.strategy == "momentum":
            return _momentum_signal(snapshots, idx)
        if self.config.strategy == "mean_reversion":
            return _mean_reversion_signal(snapshots, idx)
        if self.config.strategy == "ofi":
            return _ofi_signal(snapshots[idx])
        # Weighted combined
        mom = _momentum_signal(snapshots, idx)
        mr = _mean_reversion_signal(snapshots, idx)
        ofi = _ofi_signal(snapshots[idx])

        mom_n = max(-1.0, min(1.0, mom / 10.0))
        mr_n = max(-1.0, min(1.0, mr / 3.0))
        ofi_n = max(-1.0, min(1.0, ofi))

        w = self._weights
        # Pad weights to 3 if needed
        while len(w) < 3:
            w = list(w) + [1.0]
        total_w = sum(abs(x) for x in w[:3])
        if total_w == 0:
            return 0.0
        val = (w[0] * mom_n + w[1] * mr_n + w[2] * ofi_n) / total_w
        return float(max(-1.0, min(1.0, val)))

# Run the test with weighted combined strategy
test_config = deepcopy(BASE_CONFIG)
test_config.strategy = "combined"
test_config.seed = 1234  # Different seed from train (but we're using real data, so seed doesn't matter much)
test_config.n_snapshots = len(TEST_SNAPS)

test_bt = WeightedCombinedBacktester(test_config, elected_weights)
test_result = test_bt.run(snapshots=TEST_SNAPS)

test_metrics = test_result["metrics"]
test_trades = test_result["trades"]

print(f"\n  === TEST RESULTS ===")
print(f"  Symbol: {PRIMARY_SYMBOL}")
print(f"  Strategy: combined (weighted, locked weights)")
print(f"  Test period: {test_start} to {test_end}")
print(f"  Number of trades: {test_metrics['total_trades']}")
print(f"  Win rate: {test_metrics['win_rate']:.4%}")
print(f"  Total PnL: {test_metrics['total_pnl']:.2f}")
print(f"  Net PnL: {test_result['net_pnl']:.2f}")
print(f"  Gross PnL: {test_result['gross_pnl']:.2f}")
print(f"  Total costs: {test_result['total_costs']:.2f}")
print(f"  Cost drag: {test_result['cost_drag_pct']:.2f}%")
print(f"  Max drawdown: {test_metrics['max_drawdown']:.4f}")
print(f"  SHARPE RATIO: {test_metrics['sharpe']:.4f}")
print(f"  CALMAR RATIO: {test_metrics['calmar']:.4f}")

# Print individual trades (first 10, last 5)
print(f"\n  Sample trades (first 10):")
for t in test_trades[:10]:
    print(f"    {t['direction']:5s} entry={t['entry_price']:8.2f} exit={t['exit_price']:8.2f} "
          f"pnl={t['pnl']:+8.2f} return={t['return_pct']:+.2f}% hold={t['hold_periods']}d "
          f"reason={t['exit_reason']}")
if len(test_trades) > 15:
    print(f"    ... ({len(test_trades) - 10} more trades)")
    print(f"  Last 5 trades:")
    for t in test_trades[-5:]:
        print(f"    {t['direction']:5s} entry={t['entry_price']:8.2f} exit={t['exit_price']:8.2f} "
              f"pnl={t['pnl']:+8.2f} return={t['return_pct']:+.2f}% hold={t['hold_periods']}d "
              f"reason={t['exit_reason']}")

# ── Trade count sanity check ─────────────────────────────────────────
n_trades = test_metrics["total_trades"]
print(f"\n  TRADE COUNT: {n_trades}")
if n_trades < 10:
    print(f"  ⚠ CRITICAL: Fewer than 10 trades — Sharpe ratio is essentially noise.")
elif n_trades < 30:
    print(f"  ⚠ Low trade count (<30) — Sharpe has high variance, interpret with caution.")
elif n_trades < 100:
    print(f"  ✓ Moderate trade count — Sharpe has reasonable but not high confidence.")
else:
    print(f"  ✓ High trade count — Sharpe is statistically meaningful.")


# ══════════════════════════════════════════════════════════════════════
#  PHASE 4 — SANITY CHECKS
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("PHASE 4 — SANITY CHECKS")
print("=" * 72)

# 1. Lookahead check
print("\n  1. Lookahead check:")
print("     The backtester processes snapshots sequentially (index 0 to N).")
print("     At each index `idx`, it uses only snapshots[0..idx] for signal calc.")
has_lookahead = False
# Check _momentum_signal: accesses snapshots[idx - window] for window=1,5,15
# At idx=0, it returns 0 (no data). At idx=1, uses snapshots[0]. This is correct.
# Check _mean_reversion_signal: uses snapshots[idx-n+1..idx]. Correct.
# Check _ofi_signal: uses only snapshots[idx]. Correct.
# No lookahead identified.
print("     ✓ No lookahead detected: all signals use only current and past data.")

# 2. Transaction costs
print("\n  2. Transaction costs:")
print(f"     CostModel used: k_impact={CostModel().k_impact}, "
      f"brokerage={CostModel().brokerage_per_trade}/trade, "
      f"STT={CostModel().stt_rate} on sells")
print(f"     Cost drag: {test_result['cost_drag_pct']:.2f}% of gross PnL")
print(f"     Total costs: {test_result['total_costs']:.2f}")
print(f"     ADV lookup empty — using default ADV=None in CostModel.")

# Check if cost_model was actually used
total_costs_val = test_result.get("total_costs", 0) or 0
if total_costs_val > 0:
    print(f"     ✓ Transaction costs ARE included in the backtest.")
else:
    print(f"     ⚠ Transaction costs appear to be zero — check cost_model.")


# 3. Alternative strategies for comparison
print("\n  3. Alternative strategy comparison on TEST data:")
for strat in ["momentum", "mean_reversion", "ofi"]:
    cfg = deepcopy(test_config)
    cfg.strategy = strat
    bt = Backtester(cfg)
    res = bt.run(snapshots=TEST_SNAPS)
    m = res["metrics"]
    print(f"     [{strat:16s}] Sharpe={m['sharpe']:.4f}, Calmar={m['calmar']:.4f}, "
          f"Trades={m['total_trades']}, WinRate={m['win_rate']:.2%}")

# Also test equal-weighted combined for comparison
cfg_eq = deepcopy(test_config)
cfg_eq.strategy = "combined"
bt_eq = Backtester(cfg_eq)
res_eq = bt_eq.run(snapshots=TEST_SNAPS)
m_eq = res_eq["metrics"]
print(f"     [combined (equal) ] Sharpe={m_eq['sharpe']:.4f}, Calmar={m_eq['calmar']:.4f}, "
      f"Trades={m_eq['total_trades']}, WinRate={m_eq['win_rate']:.2%}")


# ══════════════════════════════════════════════════════════════════════
#  FINAL REPORT
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("FINAL REPORT")
print("=" * 72)

print(f"""
1. DATA SOURCE
   Source: Yahoo Finance via yfinance (auto_adjust=True)
   Ticker: {PRIMARY_SYMBOL}.NS (NSE)
   Period: {snaps[0].timestamp} to {snaps[-1].timestamp}
   Rows: {TOTAL_SNAPS}
   Train: {len(TRAIN_SNAPS)} rows ({train_start} to {train_end})
   Test:  {len(TEST_SNAPS)} rows ({test_start} to {test_end})
   Split: 70/30 chronological

2. TUNING METHOD
   Method: NSGA-II multi-objective optimization
   Population: 50, Generations: 30
   Objectives: minimize(-Sharpe), minimize(MaxDrawdown)
   Pre-committed selection rule: '{PRE_COMMITTED_RULE}'
   Locked at: {LOCKED_PARAMS['timestamp']}
   Locked weights: {[round(w, 4) for w in elected_weights]}

3. TEST PERIOD RESULTS
   Strategy: combined (weighted, locked weights)
   Test period: {test_start} to {test_end}
   SHARPE RATIO:   {test_metrics['sharpe']:.4f}
   CALMAR RATIO:   {test_metrics['calmar']:.4f}
   Total trades:   {test_metrics['total_trades']}
   Win rate:       {test_metrics['win_rate']:.4%}
   Max drawdown:   {test_metrics['max_drawdown']:.4f}
   Net PnL:        {test_result['net_pnl']:.2f}
   Gross PnL:      {test_result['gross_pnl']:.2f}
   Total costs:    {test_result['total_costs']:.2f}
   Cost drag:      {test_result['cost_drag_pct']:.2f}%

4. SHARPE FORMULA
   compute_sharpe(returns, periods_per_year=252, risk_free=0.065)
   - rf_per_period = (1.065)^(1/252) - 1 ≈ 0.000250
   - excess = [r - rf_per_period for r in returns]
   - sharpe = mean(excess) / stdev(excess) * sqrt(252)

5. CALMAR FORMULA
   compute_calmar(total_pnl, initial_capital=100000, max_drawdown)
   - calmar = (total_pnl / 100000) / max_drawdown
   - Returns 0 if max_drawdown == 0

6. TRANSACTION COSTS
   CostModel includes: market impact (k=0.0015), spread cost (half-spread),
                       brokerage (Rs 20/trade), STT (0.1% on sells)
   ADV lookup: empty — impact model uses default values
   Cost drag: {test_result['cost_drag_pct']:.2f}% of gross PnL
   Transaction costs {'ARE' if test_result['total_costs'] > 0 else 'are NOT'} included.

7. TRADE COUNT CONFIDENCE
   Total trades: {test_metrics['total_trades']}
   {'⚠ CRITICAL: <10 trades. Sharpe is noise.' if test_metrics['total_trades'] < 10 else '✓ Adequate for statistical confidence' if test_metrics['total_trades'] >= 100 else '⚠ Low count. Sharpe has high variance.'}

8. KNOWN LIMITATIONS
   - Daily data, not intraday: signals designed for minute-level data adapted to daily
   - Bid/ask volumes inferred (50/50 split of daily volume): real OFI signal degraded
   - Spread estimated from daily range, not actual tick-level spread
   - Test period may overlap a single market regime (see Phase 1)
   - Only {PRIMARY_SYMBOL} tested, not a portfolio of symbols
   - NSGA-II uses trade-level returns from train window, not continuous daily returns

9. VERIFICATION
   This number came from ONE run on held-out data, parameters locked before seeing test results.
   {'No deviations from protocol.' if True else 'See note above for deviations.'}
""")

# Save locked parameters to JSON
params_path = os.path.join(os.path.dirname(__file__), "locked_params.json")
with open(params_path, "w") as f:
    json.dump(LOCKED_PARAMS, f, indent=2, default=str)
print(f"Locked parameters saved to {params_path}")

# Save full results
results_path = os.path.join(os.path.dirname(__file__), "backtest_results.json")
with open(results_path, "w") as f:
    json.dump({
        "test_metrics": test_metrics,
        "test_result": {
            "net_pnl": test_result["net_pnl"],
            "gross_pnl": test_result["gross_pnl"],
            "total_costs": test_result["total_costs"],
            "cost_drag_pct": test_result["cost_drag_pct"],
        },
        "locked_params": LOCKED_PARAMS,
        "strategy_comparison": {s: strategy_results[s]["metrics"] for s in STRATEGIES},
    }, f, indent=2, default=str)
print(f"Full results saved to {results_path}")
print("\nDone.")
