#!/usr/bin/env python3
"""
AlphaCore — NSGA-II vs Equal Signal Weight Comparison

Compares two signal combination strategies on held-out synthetic GBM data:
  Arm A: NSGA-II-optimized weights from locked_params.json
  Arm B: naive equal weighting (1/3, 1/3, 1/3)

Pre-committed protocol: EXPERIMENT_PROTOCOL.md (2026-07-30 14:30 IST)
"""

from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engines.backtester import (
    BacktestConfig,
    Snapshot,
    Trade,
    _get_direction,
    _mean_reversion_signal,
    _momentum_signal,
    _ofi_signal,
    generate_snapshots,
)
from engines.backtest_metrics import (
    build_equity_curve,
    compute_max_drawdown,
    compute_returns_from_equity,
    compute_sharpe,
    compute_win_rate,
    full_metrics,
    stationary_bootstrap_sharpe_ci,
)
from engines.cost_model import CostModel

# ── Configuration ──────────────────────────────────────────────────────────

HELD_OUT_SEED = 2026  # provably different from seed=42 used in prior tuning
N_SNAPSHOTS = 1000
SYMBOL = "RELIANCE"

# Locked NSGA-II weights from locked_params.json
NSGAII_WEIGHTS = [0.5425832619873837, 3.520675273047467e-12, 0.45741673800909555]
EQUAL_WEIGHTS = [1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0]
WEIGHT_LABELS = ["momentum", "mean_reversion", "ofi"]


# ── Weighted Signal ───────────────────────────────────────────────────────

def weighted_combined_signal(snapshots: list[Snapshot], idx: int, weights: list[float]) -> float:
    """Weighted combination of momentum, mean-reversion, and OFI signals.

    Same normalization as _combined_signal() in backtester.py, but with
    custom weights instead of equal weighting.
    """
    mom = _momentum_signal(snapshots, idx)
    mr = _mean_reversion_signal(snapshots, idx)
    ofi = _ofi_signal(snapshots[idx])

    # Normalize each signal to [-1, 1] (same as _combined_signal)
    mom_n = max(-1.0, min(1.0, mom / 10.0))
    mr_n = max(-1.0, min(1.0, mr / 3.0))
    ofi_n = max(-1.0, min(1.0, ofi))

    w = list(weights)
    w_sum = sum(w)
    if w_sum <= 0:
        w = [1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0]
        w_sum = 1.0

    val = (w[0] * mom_n + w[1] * mr_n + w[2] * ofi_n) / w_sum
    return float(max(-1.0, min(1.0, val)))


# ── Weighted Backtester (reuses existing Backtester internals) ────────────

def run_weighted_backtest(
    snapshots: list[Snapshot],
    weights: list[float],
    config: BacktestConfig,
) -> dict:
    """Run the backtester with custom signal weights.

    This mirrors the Backtester.run() logic from backtester.py, replacing
    _combined_signal's equal weighting with the provided weight vector.
    """
    cost_model = CostModel()
    trades: list[Trade] = []
    current_capital = float(config.initial_capital)
    gross_pnl_total = 0.0
    total_costs = 0.0

    in_position = False
    direction: str | None = None
    entry_price = 0.0
    quantity = 0.0
    entry_period = -1

    for idx, snap in enumerate(snapshots):
        if not in_position:
            signal = weighted_combined_signal(snapshots, idx, weights)
            direction = _get_direction(signal, "combined")
            if direction is None:
                continue

            entry_price = snap.ask_price if direction == "LONG" else snap.bid_price
            if entry_price <= 0:
                continue
            quantity = (config.position_size_pct * current_capital) / entry_price if current_capital > 0 else 0.0
            if quantity <= 0:
                continue
            entry_period = idx
            in_position = True
            continue

        hold = idx - entry_period
        exit_reason = None

        if direction == "LONG" and snap.mid_price < entry_price * (1 - config.stop_loss_pct):
            exit_reason = "STOP_LOSS"
        elif direction == "SHORT" and snap.mid_price > entry_price * (1 + config.stop_loss_pct):
            exit_reason = "STOP_LOSS"
        elif hold >= config.hold_periods:
            exit_reason = "SIGNAL"

        if exit_reason is not None:
            exit_price = snap.bid_price if direction == "LONG" else snap.ask_price

            if direction == "LONG":
                gross_pnl = (exit_price - entry_price) * quantity
                ret = ((exit_price - entry_price) / entry_price) * 100.0 if entry_price else 0.0
                side = "SELL"
            else:
                gross_pnl = (entry_price - exit_price) * quantity
                ret = ((entry_price - exit_price) / entry_price) * 100.0 if entry_price else 0.0
                side = "BUY"

            adv = cost_model.adv_lookup.get(SYMBOL)
            trade_cost = cost_model.total_cost(
                price=exit_price,
                qty=quantity,
                adv=adv,
                spread_bps=snap.spread_bps,
                side=side,
            )
            pnl = gross_pnl - trade_cost

            trades.append(Trade(
                symbol=SYMBOL,
                strategy="weighted",
                direction=direction,
                entry_price=float(entry_price),
                exit_price=float(exit_price),
                quantity=float(quantity),
                pnl=float(pnl),
                return_pct=float(ret),
                entry_period=int(entry_period),
                exit_period=int(idx),
                hold_periods=int(hold),
                exit_reason=exit_reason,
            ))
            gross_pnl_total += float(gross_pnl)
            total_costs += float(trade_cost)
            current_capital = max(0.0, current_capital + pnl)
            in_position = False

    # Flush any open position at end of data
    if in_position and snapshots:
        idx = len(snapshots) - 1
        snap = snapshots[idx]
        exit_price = snap.bid_price if direction == "LONG" else snap.ask_price

        if direction == "LONG":
            gross_pnl = (exit_price - entry_price) * quantity
            ret = ((exit_price - entry_price) / entry_price) * 100.0 if entry_price else 0.0
            side = "SELL"
        else:
            gross_pnl = (entry_price - exit_price) * quantity
            ret = ((entry_price - entry_price) / entry_price) * 100.0 if entry_price else 0.0
            side = "BUY"

        adv = cost_model.adv_lookup.get(SYMBOL)
        trade_cost = cost_model.total_cost(
            price=exit_price,
            qty=quantity,
            adv=adv,
            spread_bps=snap.spread_bps,
            side=side,
        )
        pnl = gross_pnl - trade_cost

        trades.append(Trade(
            symbol=SYMBOL,
            strategy="weighted",
            direction=direction,
            entry_price=float(entry_price),
            exit_price=float(exit_price),
            quantity=float(quantity),
            pnl=float(pnl),
            return_pct=float(ret),
            entry_period=int(entry_period),
            exit_period=int(idx),
            hold_periods=int(idx - entry_period),
            exit_reason="END_OF_DATA",
        ))
        gross_pnl_total += float(gross_pnl)
        total_costs += float(trade_cost)
        current_capital = max(0.0, current_capital + pnl)

    trades_dict = [asdict(t) for t in trades]
    net_pnl = sum(float(t["pnl"]) for t in trades_dict)
    denom = abs(float(gross_pnl_total))
    cost_drag_pct = (total_costs / denom * 100.0) if denom > 0 else 0.0

    return {
        "config": asdict(config),
        "metrics": full_metrics(trades_dict, config.initial_capital),
        "gross_pnl": float(gross_pnl_total),
        "total_costs": float(total_costs),
        "net_pnl": float(net_pnl),
        "cost_drag_pct": float(cost_drag_pct),
        "trades": trades_dict,
        "equity_curve": build_equity_curve(config.initial_capital, trades_dict),
    }


# ── Bootstrap Confidence Interval for Paired Difference ───────────────────

def block_bootstrap_ci(
    paired_diff_series: np.ndarray,
    n_resamples: int = 2000,
    confidence: float = 0.95,
    mean_block_length: int = 10,
    seed: int = 2026,
) -> dict:
    """Block bootstrap CI for the mean of a paired-difference series.

    Uses Politis-Romano stationary bootstrap (variable-length blocks)
    to preserve autocorrelation structure.
    """
    arr = np.asarray(paired_diff_series, dtype=float)
    n = arr.size
    p = 1.0 / float(mean_block_length)
    rng = np.random.default_rng(seed)

    bootstrap_means = np.empty(n_resamples, dtype=float)

    for b in range(n_resamples):
        sample = np.empty(n, dtype=float)
        pos = 0
        start = int(rng.integers(0, n))
        while pos < n:
            block_len = int(np.ceil(rng.geometric(p)))
            block_len = min(block_len, n - pos)
            for j in range(block_len):
                sample[pos] = arr[(start + j) % n]
                pos += 1
            start = int(rng.integers(0, n))
        bootstrap_means[b] = float(np.mean(sample))

    alpha = 1.0 - confidence
    ci_lower = float(np.percentile(bootstrap_means, 100.0 * alpha / 2.0))
    ci_upper = float(np.percentile(bootstrap_means, 100.0 * (1.0 - alpha / 2.0)))

    return {
        "observed_mean": float(np.mean(arr)),
        "observed_median": float(np.median(arr)),
        "observed_std": float(np.std(arr)),
        "ci_lower": float(ci_lower),
        "ci_upper": float(ci_upper),
        "ci_width": float(ci_upper - ci_lower),
        "n_resamples": int(n_resamples),
        "n_obs": int(n),
        "confidence": float(confidence),
        "mean_block_length": int(mean_block_length),
        "excludes_zero": bool(ci_lower > 0 or ci_upper < 0),
    }


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    print("=" * 72)
    print("  AlphaCore — Signal Weight Comparison Experiment")
    print("=" * 72)
    print()
    print(f"  Pre-committed protocol: EXPERIMENT_PROTOCOL.md")
    print(f"  Held-out seed:         {HELD_OUT_SEED}")
    print(f"  Snapshots:             {N_SNAPSHOTS}")
    print(f"  Symbol:                {SYMBOL}")
    print(f"  NSGA-II weights:       {NSGAII_WEIGHTS}")
    print(f"  Equal weights:         {EQUAL_WEIGHTS}")
    print()

    # ── Step 1: Generate held-out data ──
    print(">>> Generating held-out synthetic data ...", end=" ")
    snapshots = generate_snapshots(SYMBOL, N_SNAPSHOTS, seed=HELD_OUT_SEED)
    print(f"done ({len(snapshots)} snapshots)")

    # ── Step 2: Run both arms ──
    config = BacktestConfig(
        symbol=SYMBOL,
        strategy="combined",
        n_snapshots=N_SNAPSHOTS,
        hold_periods=10,
        stop_loss_pct=0.005,
        position_size_pct=0.1,
        initial_capital=100000.0,
        seed=HELD_OUT_SEED,
    )

    print(">>> Running Arm A (NSGA-II weights) ...")
    result_a = run_weighted_backtest(snapshots, NSGAII_WEIGHTS, config)
    metrics_a = result_a["metrics"]
    print(f"      Trades: {metrics_a['total_trades']}, "
          f"PnL: ₹{metrics_a['total_pnl']:,.2f}, "
          f"Sharpe: {metrics_a['sharpe']:.4f}")

    print(">>> Running Arm B (equal weights) ...")
    result_b = run_weighted_backtest(snapshots, EQUAL_WEIGHTS, config)
    metrics_b = result_b["metrics"]
    print(f"      Trades: {metrics_b['total_trades']}, "
          f"PnL: ₹{metrics_b['total_pnl']:,.2f}, "
          f"Sharpe: {metrics_b['sharpe']:.4f}")

    # ── Step 3: Degenerate-strategy check ──
    n_trades_a = metrics_a["total_trades"]
    n_trades_b = metrics_b["total_trades"]
    degenerate = min(n_trades_a, n_trades_b) < 10
    print()
    print(f">>> Degenerate check: Arm A={n_trades_a}, Arm B={n_trades_b}")
    if degenerate:
        print("  ⚠️  WARNING: One or both arms have < 10 trades — result is likely")
        print("     inconclusive due to low sample size.")
    else:
        print("  ✅ Both arms produce adequate trade counts.")

    # ── Step 4: Build per-snapshot equity curves ──
    # Both arms start at the same initial capital and process the same snapshots.
    # We build a per-snapshot equity curve by applying trade PnL at the exit period.
    eq_a = [config.initial_capital] * len(snapshots)
    eq_b = [config.initial_capital] * len(snapshots)

    for t in result_a["trades"]:
        period = int(t["exit_period"])
        pnl = float(t["pnl"])
        for i in range(period, len(snapshots)):
            eq_a[i] += pnl

    for t in result_b["trades"]:
        period = int(t["exit_period"])
        pnl = float(t["pnl"])
        for i in range(period, len(snapshots)):
            eq_b[i] += pnl

    # Per-snapshot paired difference
    paired_diff = np.array(eq_a, dtype=float) - np.array(eq_b, dtype=float)

    # ── Step 5: Bootstrap CI on paired difference ──
    print(">>> Computing block bootstrap CI (2,000 resamples, mean_block=10) ...")
    ci_paired = block_bootstrap_ci(paired_diff, n_resamples=2000, mean_block_length=10, seed=2026)
    print(f"      Mean diff (A−B):  ₹{ci_paired['observed_mean']:,.2f}")
    print(f"      Median diff:      ₹{ci_paired['observed_median']:,.2f}")
    print(f"      95% CI:           [₹{ci_paired['ci_lower']:,.2f}, ₹{ci_paired['ci_upper']:,.2f}]")
    print(f"      Excludes zero:    {ci_paired['excludes_zero']}")

    # ── Step 6: Sharpe CIs for each arm separately ──
    # Use the trade-event equity curve (from build_equity_curve) for consistency
    # with the full_metrics() Sharpe reported in the summary table.
    print(">>> Computing stationary bootstrap Sharpe CIs (2,000 resamples) ...")
    eq_a_trade = build_equity_curve(config.initial_capital, result_a["trades"])
    eq_b_trade = build_equity_curve(config.initial_capital, result_b["trades"])
    returns_a = compute_returns_from_equity(eq_a_trade)
    returns_b = compute_returns_from_equity(eq_b_trade)

    ci_sharpe_a = stationary_bootstrap_sharpe_ci(
        returns_a, n_bootstrap=2000, mean_block_length=10, seed=2026
    )
    ci_sharpe_b = stationary_bootstrap_sharpe_ci(
        returns_b, n_bootstrap=2000, mean_block_length=10, seed=2026
    )

    print(f"      Arm A Sharpe:  {ci_sharpe_a['sharpe']:.4f}  "
          f"95% CI: [{ci_sharpe_a['ci_lower']:.4f}, {ci_sharpe_a['ci_upper']:.4f}]")
    print(f"      Arm B Sharpe:  {ci_sharpe_b['sharpe']:.4f}  "
          f"95% CI: [{ci_sharpe_b['ci_lower']:.4f}, {ci_sharpe_b['ci_upper']:.4f}]")

    # Check whether Sharpe CIs overlap
    sharpe_overlap = not (ci_sharpe_a["ci_upper"] < ci_sharpe_b["ci_lower"] or
                          ci_sharpe_b["ci_upper"] < ci_sharpe_a["ci_lower"])

    # ── Step 7: Full metrics for comparison ──
    def win_rate_info(trades_list):
        pnls = [float(t["pnl"]) for t in trades_list]
        wins = sum(1 for p in pnls if p > 0)
        return wins, len(pnls), sum(pnls)

    wa, ta, pa = win_rate_info(result_a["trades"])
    wb, tb, pb = win_rate_info(result_b["trades"])

    print()
    print("─" * 72)
    print("  RESULTS SUMMARY")
    print("─" * 72)
    print(f"  {'Metric':<30} {'Arm A (NSGA-II)':<20} {'Arm B (Equal)':<20}")
    print(f"  {'-'*30} {'-'*20} {'-'*20}")
    print(f"  {'Total PnL (INR)':<30} {metrics_a['total_pnl']:<20,.2f} {metrics_b['total_pnl']:<20,.2f}")
    print(f"  {'Sharpe':<30} {metrics_a['sharpe']:<20.4f} {metrics_b['sharpe']:<20.4f}")
    print(f"  {'Max Drawdown':<30} {metrics_a['max_drawdown']:<20.4f} {metrics_b['max_drawdown']:<20.4f}")
    print(f"  {'Win Rate':<30} {metrics_a['win_rate']:<20.2%} {metrics_b['win_rate']:<20.2%}")
    print(f"  {'Total Trades':<30} {metrics_a['total_trades']:<20} {metrics_b['total_trades']:<20}")
    print(f"  {'Wins / Losses':<30} {wa}/{ta-wa:<17} {wb}/{tb-wb:<17}")
    print(f"  {'Cost Drag':<30} {result_a['cost_drag_pct']:<19.1f}% {result_b['cost_drag_pct']:<19.1f}%")
    print()
    print("  PAIRED DIFFERENCE (equity A − B, per snapshot):")
    print(f"    Mean diff:  ₹{ci_paired['observed_mean']:,.2f}")
    print(f"    Median diff: ₹{ci_paired['observed_median']:,.2f}")
    print(f"    95% CI:     [₹{ci_paired['ci_lower']:,.2f}, ₹{ci_paired['ci_upper']:,.2f}]")
    print(f"    Width:      ₹{ci_paired['ci_width']:,.2f}")
    print(f"    Excludes zero: {ci_paired['excludes_zero']}")
    print()
    print("  SHARPE COMPARISON:")
    print(f"    Arm A Sharpe: {ci_sharpe_a['sharpe']:.4f} "
          f"[{ci_sharpe_a['ci_lower']:.4f}, {ci_sharpe_a['ci_upper']:.4f}]")
    print(f"    Arm B Sharpe: {ci_sharpe_b['sharpe']:.4f} "
          f"[{ci_sharpe_b['ci_lower']:.4f}, {ci_sharpe_b['ci_upper']:.4f}]")
    print(f"    CIs overlap: {sharpe_overlap}")

    # ── Step 8: Save results ──
    output = {
        "protocol": "EXPERIMENT_PROTOCOL.md",
        "held_out_seed": HELD_OUT_SEED,
        "n_snapshots": N_SNAPSHOTS,
        "symbol": SYMBOL,
        "weights": {
            "nsgaii": {"values": NSGAII_WEIGHTS, "labels": WEIGHT_LABELS},
            "equal": {"values": EQUAL_WEIGHTS, "labels": WEIGHT_LABELS},
        },
        "arm_a": {
            "label": "NSGA-II weights",
            "weights": NSGAII_WEIGHTS,
            "metrics": metrics_a,
            "trades": result_a["trades"],
            "equity_curve": eq_a,
        },
        "arm_b": {
            "label": "Equal weights",
            "weights": EQUAL_WEIGHTS,
            "metrics": metrics_b,
            "trades": result_b["trades"],
            "equity_curve": eq_b,
        },
        "paired_difference": {
            "label": "equity_A - equity_B",
            **ci_paired,
        },
        "sharpe_comparison": {
            "arm_a": ci_sharpe_a,
            "arm_b": ci_sharpe_b,
            "cis_overlap": sharpe_overlap,
        },
        "degenerate_checks": {
            "arm_a_trades": n_trades_a,
            "arm_b_trades": n_trades_b,
            "degenerate": degenerate,
        },
    }

    output_path = Path(__file__).resolve().parent.parent.parent / "weight_comparison_results.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n>>> Results saved to {output_path}")

    # ── Bottom line ──
    print()
    print("─" * 72)
    if ci_paired["excludes_zero"]:
        direction = "higher" if ci_paired["observed_mean"] > 0 else "lower"
        print(f"  VERDICT: Paired equity difference excludes zero at 95% confidence.")
        print(f"  Arm A (NSGA-II) equity is significantly {direction} than Arm B (equal).")
    elif degenerate:
        print(f"  VERDICT: INCONCLUSIVE — one or both arms produced too few trades.")
    else:
        print(f"  VERDICT: Paired equity difference does NOT exclude zero at 95% confidence.")
        print(f"  No statistically significant difference detected between arms.")
    print("─" * 72)

if __name__ == "__main__":
    main()
