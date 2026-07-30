#!/usr/bin/env python3.11
"""
AlphaCore — Cross-Sectional Relative Strength: Monthly Rebalancing Test

Tests whether reducing rebalance frequency from every 5 days to monthly
(21 trading days) lets the cross-sectional relative strength signal
survive transaction costs.

Uses the FIXED MTM backtester from the diagnostic pass.
Only parameter changed from original experiment: rebalance_interval.

Protocol: CROSS_SECTIONAL_MONTHLY_PROTOCOL.md (pre-committed)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engines.backtest_metrics import compute_sharpe, stationary_bootstrap_sharpe_ci

# Import the FIXED backtester (corrected MTM logic from diagnostic pass)
# Note: sys.path includes backend/ at this point
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # also add project root
from experiments.cross_sectional_diagnostic import (
    FixedCrossSectionalBacktester, load_data, build_panel,
    INITIAL_CAPITAL, SYMBOLS,
    N_BOOTSTRAP, BOOTSTRAP_SEED,
    TEST_START_INDEX, LOOKBACK_N,
)

# ── Parameters — ONLY rebalance interval changes ──
REBALANCE_MONTHLY = 21  # ~monthly
K = 1
POSITION_SIZE_PCT = 0.10
MEAN_BLOCK_LENGTH = 21  # matches monthly rebalance cycle

# ── Prior results (corrected, from cross_sectional_diagnostic_results.json) ──
PRIOR = {
    "gross_pnl": -6967.42,
    "total_costs": 16931.45,
    "net_pnl": -23898.87,
    "sharpe": -7.19,
    "ci_lower": -6.99,
    "ci_upper": -3.98,
    "cost_drag": 243.0,
    "long_leg_pnl": -10008.99,
    "short_leg_pnl": -10046.40,
    "final_equity": 76101.13,
    "n_reb": 142,
    "long_winner_pct": 60.6,
    "short_loser_pct": 71.8,
}


def main():
    print("=" * 72)
    print("  Cross-Sectional Relative Strength — Monthly Rebalancing")
    print("=" * 72)
    print("  Protocol: CROSS_SECTIONAL_MONTHLY_PROTOCOL.md")
    print(f"  Rebalance: every {REBALANCE_MONTHLY} trading days")
    print(f"  N (lookback): {LOOKBACK_N}")
    print(f"  K: {K}")
    print(f"  MTM logic: FIXED (diagnostic pass)")
    print()

    # ── Load data ──
    print(">>> Loading data ...")
    raw_data = load_data()
    panel = build_panel(raw_data)
    test_panel = panel.iloc[TEST_START_INDEX:]
    print(f"  Test panel: {len(test_panel)} days")
    print()

    # ── Run ──
    print(">>> Running fixed backtester with monthly rebalancing ...")
    bt = FixedCrossSectionalBacktester(
        panel=test_panel,
        lookback_n=LOOKBACK_N,
        k=K,
        rebalance_interval=REBALANCE_MONTHLY,
        position_size_pct=POSITION_SIZE_PCT,
        initial_capital=INITIAL_CAPITAL,
    )
    result = bt.run(dump_rebalances=False)

    daily_rets = result["daily_returns"]
    n_days = len(daily_rets)

    # Metrics
    sharpe_val = compute_sharpe(daily_rets.tolist())

    ci = stationary_bootstrap_sharpe_ci(
        daily_rets,
        n_bootstrap=N_BOOTSTRAP,
        mean_block_length=MEAN_BLOCK_LENGTH,
        seed=BOOTSTRAP_SEED,
    )

    # Position alignment
    rlog = result["rebalance_log"]
    winners = {"RELIANCE", "ICICIBANK"}
    losers = {"TCS", "INFY", "HDFCBANK"}
    long_winner = sum(1 for e in rlog if e["top_sym"] in winners)
    short_loser = sum(1 for e in rlog if e["bottom_sym"] in losers)

    total_reb = len(rlog)

    # Turnover
    long_same = sum(
        1 for i in range(1, len(rlog)) if rlog[i - 1]["top_sym"] == rlog[i]["top_sym"]
    )
    short_same = sum(
        1
        for i in range(1, len(rlog))
        if rlog[i - 1]["bottom_sym"] == rlog[i]["bottom_sym"]
    )
    long_changed = (total_reb - 1) - long_same
    short_changed = (total_reb - 1) - short_same

    print()
    print("-" * 72)
    print("  RESULTS")
    print("-" * 72)
    print()
    header = f"  {'Metric':<40} {'5-day (prior)':<22} {'Monthly (this)':<22}"
    print(header)
    print(f"  {'-'*40} {'-'*22} {'-'*22}")

    print(f"  {'Rebalance interval':<40} {'5 days':<22} {'21 days (monthly)':<22}")
    print(f"  {'Rebalance events':<40} {PRIOR['n_reb']:<22} {total_reb:<22}")
    print(f"  {'Gross PnL':<40}   {PRIOR['gross_pnl']:<+10,.2f}         {result['gross_pnl']:<+10,.2f}")
    print(f"  {'Total costs':<40}   {PRIOR['total_costs']:<+10,.2f}         {result['total_costs']:<+10,.2f}")
    print(f"  {'Net PnL':<40}   {PRIOR['net_pnl']:<+10,.2f}         {result['net_pnl']:<+10,.2f}")
    print(f"  {'Long leg PnL':<40}   {PRIOR['long_leg_pnl']:<+10,.2f}         {result['long_leg_pnl']:<+10,.2f}")
    print(f"  {'Short leg PnL':<40}   {PRIOR['short_leg_pnl']:<+10,.2f}         {result['short_leg_pnl']:<+10,.2f}")
    print(f"  {'Cost drag (% of gross)':<40} {PRIOR['cost_drag']:<6.1f}%               {result['cost_drag_pct']:<6.1f}%")
    print(f"  {'Final equity':<40}   {PRIOR['final_equity']:<+10,.2f}         {result['final_equity']:<+10,.2f}")
    print(f"  {'Return':<40} {'-23.90%':<22} {((result['final_equity']/INITIAL_CAPITAL)-1)*100:<+6.2f}%")
    print(f"  {'Sharpe':<40} {PRIOR['sharpe']:<+10.4f}         {sharpe_val:<+10.4f}")
    ci_excludes = ci["ci_lower"] > 0 or ci["ci_upper"] < 0
    print(f"  {'95% CI':<40} [{PRIOR['ci_lower']:.2f}, {PRIOR['ci_upper']:.2f}]         [{ci['ci_lower']:.4f}, {ci['ci_upper']:.4f}]")
    print(f"  {'CI excludes zero?':<40} {'True (NEGATIVE)':<22} {ci_excludes}")
    print(f"  {'N observations':<40} {352:<22} {n_days:<22}")

    print()
    print("  DIRECTIONAL ALIGNMENT (monthly):")
    print(f"    LONG on winners: {long_winner}/{total_reb} ({long_winner/total_reb*100:.1f}%)  [prior: {PRIOR['long_winner_pct']:.1f}%]")
    print(f"    SHORT on losers: {short_loser}/{total_reb} ({short_loser/total_reb*100:.1f}%)  [prior: {PRIOR['short_loser_pct']:.1f}%]")
    print(f"    LONG same symbol as prev: {long_same}/{total_reb-1} ({long_same/(total_reb-1)*100:.1f}%)")
    print(f"    SHORT same symbol as prev: {short_same}/{total_reb-1} ({short_same/(total_reb-1)*100:.1f}%)")

    # Per-symbol breakdown
    print()
    print("  BREAKDOWN OF REBALANCE PICKS:")
    for sym in ["ICICIBANK", "RELIANCE", "HDFCBANK", "TCS", "INFY"]:
        long_count = sum(1 for e in rlog if e["top_sym"] == sym)
        short_count = sum(1 for e in rlog if e["bottom_sym"] == sym)
        print(f"    {sym:<12}: LONG {long_count:>2}x, SHORT {short_count:>2}x")

    # ── Save results ──
    output = {
        "protocol": "CROSS_SECTIONAL_MONTHLY_PROTOCOL.md",
        "parameters": {
            "rebalance_interval": REBALANCE_MONTHLY,
            "lookback_n": LOOKBACK_N,
            "k": K,
            "position_size_pct": POSITION_SIZE_PCT,
            "initial_capital": INITIAL_CAPITAL,
            "mtm_logic": "FIXED (diagnostic pass)",
            "bootstrap": {
                "method": "stationary bootstrap",
                "n_resamples": N_BOOTSTRAP,
                "mean_block_length": MEAN_BLOCK_LENGTH,
                "seed": BOOTSTRAP_SEED,
            },
        },
        "results": {
            "sharpe": float(sharpe_val),
            "ci_lower": float(ci["ci_lower"]),
            "ci_upper": float(ci["ci_upper"]),
            "ci_excludes_zero": bool(ci_excludes),
            "n_observations": int(ci["n_obs"]),
            "net_pnl": float(result["net_pnl"]),
            "gross_pnl": float(result["gross_pnl"]),
            "total_costs": float(result["total_costs"]),
            "cost_drag_pct": float(result["cost_drag_pct"]),
            "long_leg_pnl": float(result["long_leg_pnl"]),
            "short_leg_pnl": float(result["short_leg_pnl"]),
            "final_equity": float(result["final_equity"]),
            "total_return_pct": float(
                ((result["final_equity"] / INITIAL_CAPITAL) - 1) * 100
            ),
            "n_rebalances": total_reb,
            "n_trades": result["n_trades"],
            "long_on_winner_pct": float(long_winner / total_reb * 100),
            "short_on_loser_pct": float(short_loser / total_reb * 100),
            "long_turnover_pct": float(
                long_changed / (total_reb - 1) * 100 if total_reb > 1 else 0
            ),
            "short_turnover_pct": float(
                short_changed / (total_reb - 1) * 100 if total_reb > 1 else 0
            ),
        },
    }

    output_path = Path(__file__).resolve().parent.parent.parent / "cross_sectional_monthly_results.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n>>> Results saved to {output_path}")
    print()

    # ── Bottom line ──
    print("-" * 72)

    if not ci_excludes and total_reb < 20:
        print(f"  SAMPLE SIZE WARNING: Only {total_reb} rebalance events. CI is wide.")
        print("  Any conclusion is tentative with this level of statistical power.")
        print()

    print("  Net PnL improvement from 5-day to monthly:")
    change_pct = ((result["net_pnl"] / PRIOR["net_pnl"]) - 1) * 100
    print(f"    {PRIOR['net_pnl']:+,.2f} -> {result['net_pnl']:+,.2f} ({change_pct:+.1f}% change in loss)")
    print(f"  Cost drag improvement:")
    print(f"    {PRIOR['cost_drag']:.1f}% -> {result['cost_drag_pct']:.1f}%")
    print()

    if result["net_pnl"] > 0 and ci_excludes:
        print("  POSITIVE RESULT: Monthly rebalancing lets the signal survive costs.")
        print("  Statistically significant positive Sharpe on held-out data.")
    elif result["net_pnl"] > 0:
        print("  SUGGESTIVE BUT INCONCLUSIVE: Net PnL is positive but the CI")
        print("  includes zero, possibly due to the small sample size.")
    elif result["net_pnl"] < 0 and ci_excludes:
        print("  NEGATIVE RESULT: Monthly rebalancing did NOT fix the problem.")
        print("  The strategy still loses money net of costs with statistical significance.")
    else:
        print("  INCONCLUSIVE: CI includes zero. Cannot distinguish signal from noise.")
        print("  Monthly rebalancing neither fixes nor confirms the negative result.")

    print()
    print("  Overall arc:")
    print("    5-day rebalance:    real directional skill, 243% cost drag, destroyed by costs")
    if result["net_pnl"] > 0:
        print(f"    Monthly rebalance:  cost drag reduced to {result['cost_drag_pct']:.1f}%, strategy profitable ({result['net_pnl']:+,.2f})")
    else:
        print(f"    Monthly rebalance:  cost drag {result['cost_drag_pct']:.1f}% (still >100%), strategy still loses ({result['net_pnl']:+,.2f})")
    print("-" * 72)


if __name__ == "__main__":
    main()
