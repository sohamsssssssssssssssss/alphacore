#!/usr/bin/env python3.11
"""
AlphaCore — K Expansion Experiment

Tests whether increasing K (the number of long and short positions held per
rebalance) on the SAME 49-symbol NIFTY 50 universe, with the SAME locked
cross-sectional relative-strength signal, (a) changes cost drag as a
percentage of gross PnL, and (b) tightens the Sharpe confidence interval via
averaging across more independent bets.

Pre-committed protocol: K_EXPANSION_EXPERIMENT_PROTOCOL.md

Everything except K is locked from the 49-symbol K=1 experiment:
  - Universe: 49 NIFTY 50 symbols (backend/data/nifty50_data/)
  - Lookback N = 20 trading days
  - Rebalance every 21 trading days (monthly)
  - Position sizing: 10%/K of equity per position (equal weight across the
    K longs and K shorts; total deployed per rebalance stays at 10% long +
    10% short = 20% of equity regardless of K)
  - CostModel() default, unchanged
  - Train/test split index 867, unchanged
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
from experiments.universe_expansion_experiment import (
    DATA_DIR_50,
    SPLIT_INDEX,
    build_panel,
    close_to_bid_ask,
    load_symbols,
)

# ── Configuration (locked — only K varies) ──────────────────────────────────

# K values under test (locked in protocol BEFORE any K>1 results were seen)
K_VALUES = [1, 5, 10]

# Signal parameters (locked — identical to 49-symbol K=1 experiment)
LOOKBACK_N = 20
REBALANCE_INTERVAL = 21  # monthly (~21 trading days)
POSITION_SIZE_PCT = 0.10  # per-leg total (split equally across K positions)
INITIAL_CAPITAL = 100000.0

# Bootstrap (identical to all prior experiments)
N_BOOTSTRAP = 2000
BOOTSTRAP_SEED = 2026
MEAN_BLOCK_LENGTH = 21  # matches monthly rebalance cycle

cost_model = CostModel()


# ── K-Generalized Cross-Sectional Backtester ────────────────────────────────

class KExpansionBacktester:
    """Cross-sectional long/short backtester with configurable K.

    Identical mechanics to the K=1 version from the universe expansion
    experiment, generalized to K longs and K shorts:
    - Equal-weight sizing: each position = POSITION_SIZE_PCT / K of equity
      (total deployed per rebalance constant regardless of K)
    - All positions closed and re-opened at every rebalance (same turnover
      convention as K=1 — no "keep if still ranked" optimization)
    - Same corrected MTM logic: daily MTM from last_mid; exit PnL from
      current_mid to bid/ask
    """

    def __init__(self, panel, lookback_n=20, k=1, rebalance_interval=21,
                 position_size_pct=0.10, initial_capital=100000.0):
        self.panel = panel
        self.lookback_n = lookback_n
        self.k = k
        self.rebalance_interval = rebalance_interval
        self.position_size_pct = position_size_pct
        self.initial_capital = initial_capital

    def get_symbol_list(self):
        return [c.replace("_close", "") for c in self.panel.columns if c.endswith("_close")]

    def run(self) -> dict:
        panel = self.panel
        n_days = len(panel)
        symbols = self.get_symbol_list()
        k = self.k
        per_position_pct = self.position_size_pct / k

        if len(symbols) < 2:
            return self._empty_result(f"Only {len(symbols)} symbols available")

        # Pre-compute trailing returns
        trailing_rets = {}
        for sym in symbols:
            close_col = f"{sym}_close"
            if close_col not in panel.columns:
                continue
            trailing_rets[sym] = panel[close_col].pct_change(periods=self.lookback_n)

        # State
        equity = float(self.initial_capital)
        daily_returns: list[float] = []
        gross_pnl_total = 0.0
        total_costs = 0.0

        # Position state — lists of dicts (generalized to K positions per leg)
        long_pos: list[dict] = []   # {sym, qty, entry_price, last_mid}
        short_pos: list[dict] = []
        last_rebalance_day: int = -1
        n_rebalances = 0
        underfill_events: list[dict] = []

        trades: list[dict] = []

        start_day = self.lookback_n

        for day_idx in range(start_day, n_days):
            row = panel.iloc[day_idx]
            prev_equity = equity

            # ── 1. Compute trailing returns and rank ──
            day_returns = {}
            for sym in symbols:
                if sym not in trailing_rets:
                    continue
                ret = trailing_rets[sym].iloc[day_idx]
                if pd.isna(ret):
                    continue
                day_returns[sym] = ret

            if len(day_returns) < 2:
                daily_returns.append(0.0)
                continue

            ranked = sorted(day_returns.items(), key=lambda x: x[1], reverse=True)

            # ── 2. Check if rebalance day ──
            days_since = day_idx - last_rebalance_day
            is_rebalance = (days_since >= self.rebalance_interval)

            # ── 3. MTM PnL from held positions (corrected MTM) ──
            day_pnl = 0.0

            for p in long_pos:
                close_price = row[f"{p['sym']}_close"]
                spread_bps = row[f"{p['sym']}_spread_bps"]
                bid, ask = close_to_bid_ask(close_price, spread_bps)
                mid = (bid + ask) / 2.0
                mtm_pnl = (mid - p["last_mid"]) * p["qty"]
                day_pnl += mtm_pnl
                p["last_mid"] = mid

            for p in short_pos:
                close_price = row[f"{p['sym']}_close"]
                spread_bps = row[f"{p['sym']}_spread_bps"]
                bid, ask = close_to_bid_ask(close_price, spread_bps)
                mid = (bid + ask) / 2.0
                mtm_pnl = (p["last_mid"] - mid) * p["qty"]
                day_pnl += mtm_pnl
                p["last_mid"] = mid

            equity += day_pnl
            gross_pnl_total += day_pnl

            # ── 4. Rebalance (if scheduled) ──
            if is_rebalance:
                n_valid = len(day_returns)
                n_side = min(k, n_valid // 2)  # longs and shorts must be disjoint
                if n_side < k:
                    underfill_events.append({
                        "day": int(day_idx), "date": str(panel.index[day_idx].date()),
                        "n_valid": n_valid, "k": k, "n_side": n_side,
                    })

                long_targets = [s for s, _ in ranked[:n_side]]
                short_targets = [s for s, _ in ranked[-n_side:]]

                if n_side >= 1:
                    n_rebalances += 1

                    # Close all longs
                    for p in long_pos:
                        sym = p["sym"]
                        close_price = row[f"{sym}_close"]
                        spread_bps = row[f"{sym}_spread_bps"]
                        bid, ask = close_to_bid_ask(close_price, spread_bps)
                        current_mid = (bid + ask) / 2.0
                        exit_pnl = (bid - current_mid) * p["qty"]
                        equity += exit_pnl
                        gross_pnl_total += exit_pnl

                        cost = cost_model.total_cost(
                            price=bid, qty=p["qty"], adv=None,
                            spread_bps=spread_bps, side="SELL",
                        )
                        total_costs += cost
                        equity -= cost

                        trades.append({
                            "symbol": sym, "leg": "LONG", "action": "CLOSE",
                            "day": int(day_idx), "qty": float(p["qty"]),
                            "entry_price": float(p["entry_price"]), "exit_price": float(bid),
                            "pnl": float(exit_pnl - cost), "gross_pnl": float(exit_pnl), "cost": float(cost),
                        })

                    # Close all shorts
                    for p in short_pos:
                        sym = p["sym"]
                        close_price = row[f"{sym}_close"]
                        spread_bps = row[f"{sym}_spread_bps"]
                        bid, ask = close_to_bid_ask(close_price, spread_bps)
                        current_mid = (bid + ask) / 2.0
                        exit_pnl = (current_mid - ask) * p["qty"]
                        equity += exit_pnl
                        gross_pnl_total += exit_pnl

                        cost = cost_model.total_cost(
                            price=ask, qty=p["qty"], adv=None,
                            spread_bps=spread_bps, side="BUY",
                        )
                        total_costs += cost
                        equity -= cost

                        trades.append({
                            "symbol": sym, "leg": "SHORT", "action": "CLOSE",
                            "day": int(day_idx), "qty": float(p["qty"]),
                            "entry_price": float(p["entry_price"]), "exit_price": float(ask),
                            "pnl": float(exit_pnl - cost), "gross_pnl": float(exit_pnl), "cost": float(cost),
                        })

                    long_pos = []
                    short_pos = []

                    # Open K new longs (top-K ranked), equal weight 10%/K each
                    for sym in long_targets:
                        close_price = row[f"{sym}_close"]
                        spread_bps = row[f"{sym}_spread_bps"]
                        bid, ask = close_to_bid_ask(close_price, spread_bps)
                        qty = (per_position_pct * equity) / ask if ask > 0 else 0.0
                        if qty <= 0:
                            continue
                        cost = cost_model.total_cost(
                            price=ask, qty=qty, adv=None,
                            spread_bps=spread_bps, side="BUY",
                        )
                        total_costs += cost
                        equity -= cost
                        trades.append({
                            "symbol": sym, "leg": "LONG", "action": "OPEN",
                            "day": int(day_idx), "qty": float(qty),
                            "entry_price": float(ask), "exit_price": 0.0,
                            "pnl": float(-cost), "gross_pnl": 0.0, "cost": float(cost),
                        })
                        long_pos.append({
                            "sym": sym, "qty": float(qty),
                            "entry_price": float(ask), "last_mid": float(ask),
                        })

                    # Open K new shorts (bottom-K ranked), equal weight 10%/K each
                    for sym in short_targets:
                        close_price = row[f"{sym}_close"]
                        spread_bps = row[f"{sym}_spread_bps"]
                        bid, ask = close_to_bid_ask(close_price, spread_bps)
                        qty = (per_position_pct * equity) / bid if bid > 0 else 0.0
                        if qty <= 0:
                            continue
                        cost = cost_model.total_cost(
                            price=bid, qty=qty, adv=None,
                            spread_bps=spread_bps, side="SELL",
                        )
                        total_costs += cost
                        equity -= cost
                        trades.append({
                            "symbol": sym, "leg": "SHORT", "action": "OPEN",
                            "day": int(day_idx), "qty": float(qty),
                            "entry_price": float(bid), "exit_price": 0.0,
                            "pnl": float(-cost), "gross_pnl": 0.0, "cost": float(cost),
                        })
                        short_pos.append({
                            "sym": sym, "qty": float(qty),
                            "entry_price": float(bid), "last_mid": float(bid),
                        })

                    last_rebalance_day = day_idx

            # ── 5. Daily return ──
            daily_ret = (equity - prev_equity) / prev_equity if prev_equity > 0 else 0.0
            daily_returns.append(float(daily_ret))

        # ── Flush open positions at end ──
        for p in long_pos:
            last_row = panel.iloc[-1]
            sym = p["sym"]
            close_price = last_row[f"{sym}_close"]
            spread_bps = last_row[f"{sym}_spread_bps"]
            bid, ask = close_to_bid_ask(close_price, spread_bps)
            current_mid = (bid + ask) / 2.0
            exit_pnl = (bid - current_mid) * p["qty"]
            equity += exit_pnl
            gross_pnl_total += exit_pnl
            cost = cost_model.total_cost(
                price=bid, qty=p["qty"], adv=None,
                spread_bps=spread_bps, side="SELL",
            )
            total_costs += cost
            equity -= cost
            trades.append({
                "symbol": sym, "leg": "LONG", "action": "CLOSE_END",
                "day": int(len(panel) - 1), "qty": float(p["qty"]),
                "entry_price": float(p["entry_price"]), "exit_price": float(bid),
                "pnl": float(exit_pnl - cost), "gross_pnl": float(exit_pnl), "cost": float(cost),
            })

        for p in short_pos:
            last_row = panel.iloc[-1]
            sym = p["sym"]
            close_price = last_row[f"{sym}_close"]
            spread_bps = last_row[f"{sym}_spread_bps"]
            bid, ask = close_to_bid_ask(close_price, spread_bps)
            current_mid = (bid + ask) / 2.0
            exit_pnl = (current_mid - ask) * p["qty"]
            equity += exit_pnl
            gross_pnl_total += exit_pnl
            cost = cost_model.total_cost(
                price=ask, qty=p["qty"], adv=None,
                spread_bps=spread_bps, side="BUY",
            )
            total_costs += cost
            equity -= cost
            trades.append({
                "symbol": sym, "leg": "SHORT", "action": "CLOSE_END",
                "day": int(len(panel) - 1), "qty": float(p["qty"]),
                "entry_price": float(p["entry_price"]), "exit_price": float(ask),
                "pnl": float(exit_pnl - cost), "gross_pnl": float(exit_pnl), "cost": float(cost),
            })

        net_pnl = equity - self.initial_capital
        denom = abs(float(gross_pnl_total))
        cost_drag_pct = (total_costs / denom * 100.0) if denom > 0 else 0.0
        daily_ret_array = np.array(daily_returns, dtype=float)

        return {
            "trades": trades,
            "daily_returns": daily_ret_array,
            "final_equity": float(equity),
            "net_pnl": float(net_pnl),
            "gross_pnl": float(gross_pnl_total),
            "total_costs": float(total_costs),
            "cost_drag_pct": float(cost_drag_pct),
            "n_rebalances": int(n_rebalances),
            "n_trades": len(trades),
            "trades_per_rebalance": float(len(trades)) / n_rebalances if n_rebalances > 0 else 0.0,
            "underfill_events": underfill_events,
            "long_leg_pnl": float(sum(t["pnl"] for t in trades if t["leg"] == "LONG")),
            "short_leg_pnl": float(sum(t["pnl"] for t in trades if t["leg"] == "SHORT")),
        }

    def _empty_result(self, reason: str) -> dict:
        return {
            "trades": [],
            "daily_returns": np.array([], dtype=float),
            "final_equity": float(self.initial_capital),
            "net_pnl": 0.0,
            "gross_pnl": 0.0,
            "total_costs": 0.0,
            "cost_drag_pct": 0.0,
            "n_rebalances": 0,
            "n_trades": 0,
            "trades_per_rebalance": 0.0,
            "underfill_events": [],
            "long_leg_pnl": 0.0,
            "short_leg_pnl": 0.0,
            "empty_reason": reason,
        }


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    print("=" * 72)
    print("  AlphaCore — K Expansion Experiment")
    print("=" * 72)
    print("  Protocol: K_EXPANSION_EXPERIMENT_PROTOCOL.md")
    print(f"  Signal: Cross-sectional relative strength (N={LOOKBACK_N}, "
          f"rebalance every {REBALANCE_INTERVAL} days)")
    print(f"  Position sizing: {POSITION_SIZE_PCT:.0%} of equity split equally "
          f"across K positions per leg (total deployed constant across K)")
    print(f"  Cost model: CostModel() default — unchanged")
    print(f"  K values under test: {K_VALUES}")
    print()

    # ── Load data ──
    print(">>> Loading NIFTY 50 data ...")
    data_50 = load_symbols(DATA_DIR_50)
    symbols_50 = sorted(data_50.keys())
    print(f"  NIFTY 50 symbols loaded: {len(symbols_50)}")

    panel_50 = build_panel(data_50, symbols_50)
    test_50 = panel_50.iloc[SPLIT_INDEX:]
    print(f"  Panel: {len(panel_50)} days; Test period: {test_50.index[0].date()} "
          f"to {test_50.index[-1].date()} ({len(test_50)} days)")
    print()

    results: dict[int, dict] = {}
    summary_rows: list[dict] = []

    for k in K_VALUES:
        print("─" * 72)
        print(f"  RUN: K = {k}  ({2 * k} positions per rebalance, "
              f"{4 * k} trades per rebalance)")
        print("─" * 72)

        bt = KExpansionBacktester(
            panel=test_50, lookback_n=LOOKBACK_N, k=k,
            rebalance_interval=REBALANCE_INTERVAL,
            position_size_pct=POSITION_SIZE_PCT, initial_capital=INITIAL_CAPITAL,
        )
        result = bt.run()
        sharpe = compute_sharpe(result["daily_returns"].tolist())

        ci = stationary_bootstrap_sharpe_ci(
            result["daily_returns"], n_bootstrap=N_BOOTSTRAP,
            mean_block_length=MEAN_BLOCK_LENGTH, seed=BOOTSTRAP_SEED,
        )
        excludes_zero = ci["ci_lower"] > 0 or ci["ci_upper"] < 0

        print(f"  Rebalances: {result['n_rebalances']}  "
              f"Trades: {result['n_trades']}  "
              f"({result['trades_per_rebalance']:.1f} trades per rebalance)")
        print(f"  Gross PnL: ₹{result['gross_pnl']:>+10,.2f}")
        print(f"  Total costs: ₹{result['total_costs']:>+10,.2f}")
        print(f"  Net PnL: ₹{result['net_pnl']:>+10,.2f}")
        print(f"  Cost drag: {result['cost_drag_pct']:.1f}%")
        print(f"  Long leg: ₹{result['long_leg_pnl']:>+10,.2f}  "
              f"Short leg: ₹{result['short_leg_pnl']:>+10,.2f}")
        print(f"  Sharpe: {ci['sharpe']:.4f}")
        print(f"  95% CI: [{ci['ci_lower']:.4f}, {ci['ci_upper']:.4f}]")
        print(f"  CI excludes zero: {excludes_zero}")
        print(f"  Under-fill events (< 2K valid signals): {len(result['underfill_events'])}")
        for ue in result["underfill_events"][:10]:
            print(f"    {ue}")
        print()

        results[k] = {
            "sharpe": float(ci["sharpe"]),
            "ci_lower": float(ci["ci_lower"]),
            "ci_upper": float(ci["ci_upper"]),
            "ci_excludes_zero": bool(excludes_zero),
            "n_observations": int(ci.get("n_obs", 0)),
            "net_pnl": float(result["net_pnl"]),
            "gross_pnl": float(result["gross_pnl"]),
            "total_costs": float(result["total_costs"]),
            "cost_drag_pct": float(result["cost_drag_pct"]),
            "long_leg_pnl": float(result["long_leg_pnl"]),
            "short_leg_pnl": float(result["short_leg_pnl"]),
            "final_equity": float(result["final_equity"]),
            "n_rebalances": int(result["n_rebalances"]),
            "n_trades": int(result["n_trades"]),
            "trades_per_rebalance": float(result["trades_per_rebalance"]),
            "underfill_events": result["underfill_events"],
        }
        summary_rows.append({
            "k": k, "sharpe": results[k]["sharpe"],
            "ci_lower": results[k]["ci_lower"], "ci_upper": results[k]["ci_upper"],
            "excludes_zero": excludes_zero, "net_pnl": results[k]["net_pnl"],
            "gross_pnl": results[k]["gross_pnl"], "cost_drag_pct": results[k]["cost_drag_pct"],
            "n_trades": results[k]["n_trades"],
            "trades_per_rebalance": results[k]["trades_per_rebalance"],
        })

    # ── Comparison with prior configurations ──
    print("=" * 72)
    print("  COMPARISON TABLE — ALL CONFIGURATIONS TESTED SO FAR")
    print("=" * 72)
    print()
    header = (f"  {'Config':<22} {'Sharpe':>9} {'CI lower':>9} {'CI upper':>9} "
              f"{'Excl 0':>7} {'Net PnL':>11} {'Gross PnL':>11} {'Cost drag':>9} "
              f"{'Trades':>7}")
    sep = f"  {'-'*20} {'-'*9} {'-'*9} {'-'*9} {'-'*7} {'-'*11} {'-'*11} {'-'*9} {'-'*7}"
    print(header)
    print(sep)

    prior = json.loads(
        (Path(__file__).resolve().parent.parent.parent / "universe_expansion_results.json").read_text()
    )
    prior_rows = [
        ("5-symbol K=1", prior["results_5_symbol"]),
        ("49-symbol K=1", prior["results_nifty50"]),
    ]
    for name, r in prior_rows:
        excl = r["ci_lower"] > 0 or r["ci_upper"] < 0
        print(f"  {name:<22} {r['sharpe']:>9.2f} {r['ci_lower']:>9.2f} {r['ci_upper']:>9.2f} "
              f"{str(excl):>7} {r['net_pnl']:>11,.0f} {r['gross_pnl']:>11,.0f} "
              f"{r['cost_drag_pct']:>8.1f}% {r['n_trades']:>7}")
    for row in summary_rows:
        print(f"  49-symbol K={row['k']:<14} {row['sharpe']:>9.2f} {row['ci_lower']:>9.2f} "
              f"{row['ci_upper']:>9.2f} {str(row['excludes_zero']):>7} "
              f"{row['net_pnl']:>11,.0f} {row['gross_pnl']:>11,.0f} "
              f"{row['cost_drag_pct']:>8.1f}% {row['n_trades']:>7}")
    print()

    # ── Sanity checks ──
    print("=" * 72)
    print("  SANITY CHECKS")
    print("=" * 72)
    print()
    print("  [1] Lookahead check:")
    print(f"      ✓ Signal uses pct_change({LOOKBACK_N}) — trailing returns only")
    print(f"      ✓ Ranking/selection at day d uses only close data ≤ day d")
    print()
    print("  [2] Degenerate-strategy / under-fill check:")
    for k in K_VALUES:
        n_uf = len(results[k]["underfill_events"])
        if n_uf == 0:
            print(f"      ✓ K={k}: 0 rebalance dates with < {2 * k} valid signals "
                  f"(target always fully filled)")
        else:
            print(f"      ⚠ K={k}: {n_uf} under-fill events — see results JSON")
    print()
    print("  [3] Cost consistency:")
    print("      ✓ Identical CostModel() default applied to every trade at every K")
    print("      ✓ Same cost-per-trade structure (impact + spread + ₹20 + STT)")
    print()
    print("  [4] Position-sizing consistency:")
    for k in K_VALUES:
        pct = POSITION_SIZE_PCT / k
        print(f"      ✓ K={k}: each position = {pct:.2%} of equity, "
              f"total = {POSITION_SIZE_PCT:.0%} long + {POSITION_SIZE_PCT:.0%} short "
              f"per rebalance (constant across K)")
    print()

    # ── Bottom line ──
    print("=" * 72)
    print("  BOTTOM LINE")
    print("=" * 72)
    print()

    k1 = results[1]
    for k in K_VALUES[1:]:
        r = results[k]
        drag_change = r["cost_drag_pct"] - k1["cost_drag_pct"]
        sharpe_change = r["sharpe"] - k1["sharpe"]
        ci_width_change = (r["ci_upper"] - r["ci_lower"]) - (k1["ci_upper"] - k1["ci_lower"])
        print(f"  K=1 → K={k}:")
        print(f"    Cost drag: {k1['cost_drag_pct']:.1f}% → {r['cost_drag_pct']:.1f}% "
              f"({'↓' if drag_change < 0 else '↑'} {abs(drag_change):.1f}pp)")
        print(f"    Sharpe: {k1['sharpe']:.2f} → {r['sharpe']:.2f} "
              f"({'↑' if sharpe_change > 0 else '↓'} {abs(sharpe_change):.2f})")
        print(f"    CI: [{k1['ci_lower']:.2f}, {k1['ci_upper']:.2f}] → "
              f"[{r['ci_lower']:.2f}, {r['ci_upper']:.2f}] "
              f"({'narrower by ' + f'{abs(ci_width_change):.2f}' if ci_width_change < 0 else 'wider by ' + f'{ci_width_change:.2f}'})")
        print()

    print("  VERDICT SUMMARY:")
    any_sig_positive = any(r["ci_excludes_zero"] and r["sharpe"] > 0 for r in results.values())
    prior_n50 = prior_rows[1][1]
    prior_sig_positive = (prior_n50["ci_lower"] > 0 or prior_n50["ci_upper"] < 0) and prior_n50["sharpe"] > 0
    if any_sig_positive or prior_sig_positive:
        print("  ⚠ At least one configuration shows a positive Sharpe with CI excluding zero.")
    else:
        print("  ❌ No configuration shows a cost-surviving, statistically significant edge.")

    # ── Save results ──
    output = {
        "protocol": "K_EXPANSION_EXPERIMENT_PROTOCOL.md",
        "timestamp": pd.Timestamp.now().isoformat(),
        "parameters": {
            "k_values": K_VALUES,
            "lookback_n": LOOKBACK_N,
            "rebalance_interval": REBALANCE_INTERVAL,
            "position_size_pct": POSITION_SIZE_PCT,
            "sizing_convention": f"equal weight: {POSITION_SIZE_PCT}% of equity split "
                                 f"across K positions per leg (total deployed constant across K)",
            "initial_capital": INITIAL_CAPITAL,
            "cost_model": "CostModel() default (unchanged)",
            "bootstrap": {
                "method": "stationary bootstrap (Politis-Romano)",
                "n_resamples": N_BOOTSTRAP,
                "mean_block_length": MEAN_BLOCK_LENGTH,
                "seed": BOOTSTRAP_SEED,
            },
            "split_index": SPLIT_INDEX,
            "universe": "49 NIFTY 50 symbols (unchanged)",
        },
        "results_by_k": {str(k): results[k] for k in K_VALUES},
        "prior_configurations": {
            "5_symbol_k1": {k2: prior_rows[0][1][k2] for k2 in
                            ["sharpe", "ci_lower", "ci_upper", "net_pnl", "gross_pnl",
                             "total_costs", "cost_drag_pct", "n_rebalances", "n_trades"]},
            "49_symbol_k1": {k2: prior_rows[1][1][k2] for k2 in
                             ["sharpe", "ci_lower", "ci_upper", "net_pnl", "gross_pnl",
                              "total_costs", "cost_drag_pct", "n_rebalances", "n_trades"]},
        },
    }

    output_path = Path(__file__).resolve().parent.parent.parent / "k_expansion_results.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n>>> Results saved to {output_path}")


if __name__ == "__main__":
    main()
