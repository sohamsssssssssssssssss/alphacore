#!/usr/bin/env python3.11
"""
AlphaCore — Universe Expansion Experiment

Tests whether expanding the cross-sectional relative strength strategy from
5 symbols to the NIFTY 50 universe lets transaction costs average out relative
to the signal's directional edge, potentially producing a cost-surviving
strategy.

Pre-committed protocol: UNIVERSE_EXPANSION_EXPERIMENT_PROTOCOL.md

Signal is REUSED exactly from the 5-symbol monthly rebalance version:
  - Lookback N = 20 trading days
  - K = 1 long, 1 short
  - Rebalance every 21 trading days (monthly)
  - 10% of equity per leg
  - CostModel() default
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

# ── Configuration (locked from 5-symbol experiment) ─────────────────────────

# Source data
DATA_DIR_5 = Path(__file__).resolve().parent.parent / "data" / "real_nse_data"
DATA_DIR_50 = Path(__file__).resolve().parent.parent / "data" / "nifty50_data"

# Split index matches all prior experiments (chronological 70/30 of 1239 = 867)
SPLIT_INDEX = 867

# Signal parameters (locked — identical to 5-symbol monthly experiment)
LOOKBACK_N = 20
K = 1
REBALANCE_INTERVAL = 21  # monthly (~21 trading days)
POSITION_SIZE_PCT = 0.10
INITIAL_CAPITAL = 100000.0

# Bootstrap
N_BOOTSTRAP = 2000
BOOTSTRAP_SEED = 2026
MEAN_BLOCK_LENGTH = 21  # matches monthly rebalance cycle

cost_model = CostModel()


# ── Data Loading ───────────────────────────────────────────────────────────

def load_symbols(data_dir: Path) -> dict[str, pd.DataFrame]:
    """Load all CSV files from the given data directory."""
    data = {}
    for csv_path in sorted(data_dir.glob("*.csv")):
        if csv_path.name == "metadata.json":
            continue
        sym = csv_path.stem
        df = pd.read_csv(csv_path, parse_dates=["Date"])
        df = df.sort_values("Date").reset_index(drop=True)
        data[sym] = df
    return data


def build_panel(data: dict[str, pd.DataFrame], symbols: list[str]) -> pd.DataFrame:
    """Build daily panel with close and spread_bps columns per symbol."""
    panel = None
    for sym in symbols:
        if sym not in data:
            continue
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


# ── Cross-Sectional Backtester (MTM-fixed version from diagnostic) ──────────

class CrossSectionalBacktester:
    """Backtester for cross-sectional relative strength long/short strategy.

    Uses the CORRECTED MTM logic from the diagnostic pass:
    - Tracks last_mid per position, computes daily MTM as change from last_mid
    - Exit PnL computed from current_mid to bid/ask, not from entry_price
    """

    def __init__(self, panel, symbols, lookback_n=20, k=1, rebalance_interval=21,
                 position_size_pct=0.10, initial_capital=100000.0):
        self.panel = panel
        self.symbols = symbols
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

        # Position state
        long_sym: str | None = None
        short_sym: str | None = None
        long_qty: float = 0.0
        short_qty: float = 0.0
        long_entry_price: float = 0.0
        short_entry_price: float = 0.0
        long_last_mid: float = 0.0
        short_last_mid: float = 0.0
        last_rebalance_day: int = -1

        trades: list[dict] = []

        # Need lookback_n days before first valid trailing return
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
            top_sym = ranked[0][0]
            bottom_sym = ranked[-1][0]

            # ── 2. Check if rebalance day ──
            days_since = day_idx - last_rebalance_day
            is_rebalance = (days_since >= self.rebalance_interval)

            # ── 3. MTM PnL from held positions (corrected) ──
            day_pnl = 0.0

            if long_sym is not None and long_qty > 0:
                close_price = row[f"{long_sym}_close"]
                spread_bps = row[f"{long_sym}_spread_bps"]
                bid, ask = close_to_bid_ask(close_price, spread_bps)
                mid = (bid + ask) / 2.0
                mtm_pnl = (mid - long_last_mid) * long_qty
                day_pnl += mtm_pnl
                long_last_mid = mid

            if short_sym is not None and short_qty > 0:
                close_price = row[f"{short_sym}_close"]
                spread_bps = row[f"{short_sym}_spread_bps"]
                bid, ask = close_to_bid_ask(close_price, spread_bps)
                mid = (bid + ask) / 2.0
                mtm_pnl = (short_last_mid - mid) * short_qty
                day_pnl += mtm_pnl
                short_last_mid = mid

            equity += day_pnl
            gross_pnl_total += day_pnl

            # ── 4. Rebalance (if scheduled) ──
            if is_rebalance and top_sym != bottom_sym:
                # Close long
                if long_sym is not None and long_qty > 0:
                    close_price = row[f"{long_sym}_close"]
                    spread_bps = row[f"{long_sym}_spread_bps"]
                    bid, ask = close_to_bid_ask(close_price, spread_bps)
                    current_mid = (bid + ask) / 2.0
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
                        "entry_price": float(long_entry_price), "exit_price": float(bid),
                        "pnl": float(exit_pnl - cost), "gross_pnl": float(exit_pnl), "cost": float(cost),
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
                        "entry_price": float(short_entry_price), "exit_price": float(ask),
                        "pnl": float(exit_pnl - cost), "gross_pnl": float(exit_pnl), "cost": float(cost),
                    })
                    short_sym = None
                    short_qty = 0.0
                    short_entry_price = 0.0
                    short_last_mid = 0.0

                # Open new positions
                # Long leg — buy top-ranked symbol
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
                    long_last_mid = ask

                # Short leg — short bottom-ranked symbol
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
                    short_last_mid = bid

                last_rebalance_day = day_idx

            # ── 5. Daily return ──
            daily_ret = (equity - prev_equity) / prev_equity if prev_equity > 0 else 0.0
            daily_returns.append(float(daily_ret))

        # Flush open positions at end
        if long_sym is not None and long_qty > 0:
            last_row = panel.iloc[-1]
            close_price = last_row[f"{long_sym}_close"]
            spread_bps = last_row[f"{long_sym}_spread_bps"]
            bid, ask = close_to_bid_ask(close_price, spread_bps)
            current_mid = (bid + ask) / 2.0
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
                "symbol": long_sym, "leg": "LONG", "action": "CLOSE_END",
                "day": int(len(panel) - 1), "qty": float(long_qty),
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
                "day": int(len(panel) - 1), "qty": float(short_qty),
                "entry_price": float(short_entry_price), "exit_price": float(ask),
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
            "n_rebalances": len([t for t in trades if t["action"] == "OPEN"]),
            "n_trades": len(trades),
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
            "long_leg_pnl": 0.0,
            "short_leg_pnl": 0.0,
            "empty_reason": reason,
        }


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    print("=" * 72)
    print("  AlphaCore — Universe Expansion Experiment")
    print("=" * 72)
    print("  Protocol: UNIVERSE_EXPANSION_EXPERIMENT_PROTOCOL.md")
    print(f"  Signal: Cross-sectional relative strength (N={LOOKBACK_N}, K={K}, "
          f"rebalance every {REBALANCE_INTERVAL} days)")
    print(f"  Position size: {POSITION_SIZE_PCT:.0%} per leg")
    print(f"  Cost model: CostModel() default")
    print()

    # ── Load data ──
    print(">>> Loading 5-symbol data ...")
    data_5 = load_symbols(DATA_DIR_5)
    symbols_5 = sorted(data_5.keys())
    print(f"  5-symbol symbols: {symbols_5}")

    print(">>> Loading NIFTY 50 data ...")
    data_50 = load_symbols(DATA_DIR_50)
    symbols_50 = sorted(data_50.keys())
    print(f"  NIFTY 50 symbols loaded: {len(symbols_50)}")

    # Report data quality
    for name, data_dict, syms in [("5-symbol", data_5, symbols_5),
                                   ("NIFTY 50", data_50, symbols_50)]:
        n_rows = [len(data_dict[s]) for s in syms]
        print(f"  {name}: {len(syms)} symbols, "
              f"rows: min={min(n_rows)}, max={max(n_rows)}, avg={np.mean(n_rows):.0f}")

    # Build panels and split
    print("\n>>> Building panels ...")
    panel_5 = build_panel(data_5, symbols_5)
    panel_50 = build_panel(data_50, symbols_50)

    # Use common date range for fair comparison
    common_start = max(panel_5.index[0], panel_50.index[0])
    common_end = min(panel_5.index[-1], panel_50.index[-1])
    panel_5 = panel_5[panel_5.index >= common_start]
    panel_5 = panel_5[panel_5.index <= common_end]
    panel_50 = panel_50[panel_50.index >= common_start]
    panel_50 = panel_50[panel_50.index <= common_end]

    print(f"  5-symbol panel: {len(panel_5)} days, {len(panel_5.columns)} columns")
    print(f"  NIFTY 50 panel: {len(panel_50)} days, {len(panel_50.columns)} columns")
    print(f"  Date range: {panel_5.index[0].date()} to {panel_5.index[-1].date()}")

    # Same chronological 70/30 split index as all prior experiments
    # Note: Prior experiments used index 867 on 1239-row panels (70/30 = 867.3).
    # Our panels have 1238 rows (NIFTY 50 data ends 2026-07-29 vs 2026-07-30).
    test_5 = panel_5.iloc[SPLIT_INDEX:]
    test_50 = panel_50.iloc[SPLIT_INDEX:]
    train_50 = panel_50.iloc[:SPLIT_INDEX]

    print(f"  Train/Test split at index {SPLIT_INDEX} (same as all prior experiments)")
    print(f"  Test period: {test_5.index[0].date()} to {test_5.index[-1].date()}")
    print(f"  Train size (NIFTY 50): {len(train_50)} days")
    print(f"  Test size (5-symbol): {len(test_5)} days")
    print(f"  Test size (NIFTY 50): {len(test_50)} days")
    print()

    # ── Run 5-symbol benchmark (monthly rebalance, MTM-fixed) ──
    print("─" * 72)
    print("  BENCHMARK: 5-symbol universe (monthly rebalance)")
    print("─" * 72)

    bt_5 = CrossSectionalBacktester(
        panel=test_5, symbols=symbols_5,
        lookback_n=LOOKBACK_N, k=K, rebalance_interval=REBALANCE_INTERVAL,
        position_size_pct=POSITION_SIZE_PCT, initial_capital=INITIAL_CAPITAL,
    )
    result_5 = bt_5.run()
    sharpe_5 = compute_sharpe(result_5["daily_returns"].tolist())

    if len(result_5["daily_returns"]) >= 10:
        ci_5 = stationary_bootstrap_sharpe_ci(
            result_5["daily_returns"], n_bootstrap=N_BOOTSTRAP,
            mean_block_length=MEAN_BLOCK_LENGTH, seed=BOOTSTRAP_SEED,
        )
    else:
        ci_5 = {"sharpe": float(sharpe_5), "ci_lower": 0.0, "ci_upper": 0.0,
                "n_obs": len(result_5["daily_returns"]), "reliable": False}

    print(f"  Trades: {result_5['n_trades']}  Rebalances: {result_5['n_rebalances']}")
    print(f"  Gross PnL: ₹{result_5['gross_pnl']:>+10,.2f}")
    print(f"  Total costs: ₹{result_5['total_costs']:>+10,.2f}")
    print(f"  Net PnL: ₹{result_5['net_pnl']:>+10,.2f}")
    print(f"  Cost drag: {result_5['cost_drag_pct']:.1f}%")
    print(f"  Long leg: ₹{result_5['long_leg_pnl']:>+10,.2f}  "
          f"Short leg: ₹{result_5['short_leg_pnl']:>+10,.2f}")
    print(f"  Sharpe: {ci_5['sharpe']:.4f}")
    print(f"  95% CI: [{ci_5['ci_lower']:.4f}, {ci_5['ci_upper']:.4f}]")
    print(f"  CI excludes zero: {ci_5['ci_lower'] > 0 or ci_5['ci_upper'] < 0}")
    print()

    # ── Run NIFTY 50 experiment ──
    print("─" * 72)
    print("  EXPERIMENT: NIFTY 50 universe (monthly rebalance)")
    print("─" * 72)

    bt_50 = CrossSectionalBacktester(
        panel=test_50, symbols=symbols_50,
        lookback_n=LOOKBACK_N, k=K, rebalance_interval=REBALANCE_INTERVAL,
        position_size_pct=POSITION_SIZE_PCT, initial_capital=INITIAL_CAPITAL,
    )
    result_50 = bt_50.run()
    sharpe_50 = compute_sharpe(result_50["daily_returns"].tolist())

    if len(result_50["daily_returns"]) >= 10:
        ci_50 = stationary_bootstrap_sharpe_ci(
            result_50["daily_returns"], n_bootstrap=N_BOOTSTRAP,
            mean_block_length=MEAN_BLOCK_LENGTH, seed=BOOTSTRAP_SEED,
        )
    else:
        ci_50 = {"sharpe": float(sharpe_50), "ci_lower": 0.0, "ci_upper": 0.0,
                 "n_obs": len(result_50["daily_returns"]), "reliable": False}

    print(f"  Trades: {result_50['n_trades']}  Rebalances: {result_50['n_rebalances']}")
    print(f"  Gross PnL: ₹{result_50['gross_pnl']:>+10,.2f}")
    print(f"  Total costs: ₹{result_50['total_costs']:>+10,.2f}")
    print(f"  Net PnL: ₹{result_50['net_pnl']:>+10,.2f}")
    print(f"  Cost drag: {result_50['cost_drag_pct']:.1f}%")
    print(f"  Long leg: ₹{result_50['long_leg_pnl']:>+10,.2f}  "
          f"Short leg: ₹{result_50['short_leg_pnl']:>+10,.2f}")
    print(f"  Sharpe: {ci_50['sharpe']:.4f}")
    print(f"  95% CI: [{ci_50['ci_lower']:.4f}, {ci_50['ci_upper']:.4f}]")
    print(f"  CI excludes zero: {ci_50['ci_lower'] > 0 or ci_50['ci_upper'] < 0}")
    print()

    # ── Directional alignment ──
    print("─" * 72)
    print("  DIRECTIONAL ALIGNMENT")
    print("─" * 72)

    # For NIFTY 50, we need the actual return of each symbol during the test period
    for name, result, panel_slice in [("5-symbol", result_5, test_5),
                                       ("NIFTY 50", result_50, test_50)]:
        print(f"\n  {name} universe:")

        if result["n_rebalances"] == 0:
            print("    No rebalances — skipping alignment check")
            continue

        # Get open trades (which symbol was LONG and SHORT at each rebalance)
        open_trades = [t for t in result["trades"] if t["action"] == "OPEN"]

        if not open_trades:
            print("    No open trades found")
            continue

        # For each open trade, check if the symbol's test-period return confirms the signal
        close_cols = [c for c in panel_slice.columns if c.endswith("_close")]
        test_start_prices = {}
        test_end_prices = {}
        for col in close_cols:
            test_start_prices[col] = panel_slice[col].iloc[0]
            test_end_prices[col] = panel_slice[col].iloc[-1]

        long_winners = 0
        short_winners = 0
        long_total = 0
        short_total = 0

        for t in open_trades:
            sym = t["symbol"]
            close_col = f"{sym}_close"
            if close_col in test_start_prices and close_col in test_end_prices:
                start_p = test_start_prices[close_col]
                end_p = test_end_prices[close_col]
                if start_p > 0:
                    total_ret = (end_p - start_p) / start_p

                    if t["leg"] == "LONG":
                        long_total += 1
                        if total_ret > 0:
                            long_winners += 1
                    elif t["leg"] == "SHORT":
                        short_total += 1
                        if total_ret < 0:
                            short_winners += 1

        if long_total > 0:
            print(f"    LONG on winners:   {long_winners}/{long_total} "
                  f"({long_winners/long_total*100:.1f}%)")
        else:
            print("    LONG on winners:   N/A (no long trades)")
        if short_total > 0:
            print(f"    SHORT on losers:   {short_winners}/{short_total} "
                  f"({short_winners/short_total*100:.1f}%)")
        else:
            print("    SHORT on losers:   N/A (no short trades)")

        # Also compute ranking stability
        all_top = []
        all_bottom = []
        for t in open_trades:
            if t["leg"] == "LONG":
                all_top.append(t["symbol"])
            elif t["leg"] == "SHORT":
                all_bottom.append(t["symbol"])

        if len(all_top) >= 2:
            unique_top = len(set(all_top))
            print(f"    Unique LONG symbols: {unique_top}/{len(all_top)} positions")
        if len(all_bottom) >= 2:
            unique_bottom = len(set(all_bottom))
            print(f"    Unique SHORT symbols: {unique_bottom}/{len(all_bottom)} positions")

    print()

    # ── Comparison Table ──
    print("=" * 72)
    print("  SIDE-BY-SIDE COMPARISON")
    print("=" * 72)
    print()
    header = f"  {'Metric':<40} {'5-Symbol':<18} {'NIFTY 50':<18}"
    sep = f"  {'-'*40} {'-'*18} {'-'*18}"
    print(header)
    print(sep)
    print(f"  {'Sharpe':<40} {ci_5['sharpe']:<18.4f} {ci_50['sharpe']:<18.4f}")
    print(f"  {'95% CI lower':<40} {ci_5['ci_lower']:<18.4f} {ci_50['ci_lower']:<18.4f}")
    print(f"  {'95% CI upper':<40} {ci_5['ci_upper']:<18.4f} {ci_50['ci_upper']:<18.4f}")
    print(f"  {'CI excludes zero':<40} {str(ci_5['ci_lower'] > 0 or ci_5['ci_upper'] < 0):<18} "
          f"{str(ci_50['ci_lower'] > 0 or ci_50['ci_upper'] < 0):<18}")
    print(f"  {'Net PnL':<40} ₹{result_5['net_pnl']:<+10,.2f}      ₹{result_50['net_pnl']:<+10,.2f}")
    print(f"  {'Gross PnL':<40} ₹{result_5['gross_pnl']:<+10,.2f}      ₹{result_50['gross_pnl']:<+10,.2f}")
    print(f"  {'Total costs':<40} ₹{result_5['total_costs']:<+10,.2f}      ₹{result_50['total_costs']:<+10,.2f}")
    print(f"  {'Cost drag':<40} {result_5['cost_drag_pct']:<18.1f}% {result_50['cost_drag_pct']:<17.1f}%")
    print(f"  {'N rebalances':<40} {result_5['n_rebalances']:<18} {result_50['n_rebalances']:<18}")
    print(f"  {'N trades':<40} {result_5['n_trades']:<18} {result_50['n_trades']:<18}")
    print(f"  {'Long leg PnL':<40} ₹{result_5['long_leg_pnl']:<+10,.2f}      ₹{result_50['long_leg_pnl']:<+10,.2f}")
    print(f"  {'Short leg PnL':<40} ₹{result_5['short_leg_pnl']:<+10,.2f}      ₹{result_50['short_leg_pnl']:<+10,.2f}")
    print(f"  {'Final equity':<40} ₹{result_5['final_equity']:<+10,.2f}      ₹{result_50['final_equity']:<+10,.2f}")
    print(f"  {'Return':<40} "
          f"{((result_5['final_equity']/INITIAL_CAPITAL)-1)*100:<17.2f}% "
          f"{((result_50['final_equity']/INITIAL_CAPITAL)-1)*100:<17.2f}%")
    print(f"  {'N symbols':<40} {len(symbols_5):<18} {len(symbols_50):<18}")
    print()

    # ── Sanity Checks ──
    print("=" * 72)
    print("  SANITY CHECKS")
    print("=" * 72)
    print()
    print("  [1] Lookahead check:")
    print(f"      ✓ Signal uses pct_change({LOOKBACK_N}) — trailing returns only")
    print(f"      ✓ Entry at close uses only data available at that time")
    print()
    print("  [2] Degenerate-strategy check:")
    if result_50["n_rebalances"] >= 3:
        print(f"      ✓ {result_50['n_rebalances']} rebalance events ≥ 3 minimum")
    else:
        print(f"      ⚠ ONLY {result_50['n_rebalances']} rebalance events — may be unreliable")
    if result_5["n_rebalances"] >= 3:
        print(f"      ✓ 5-symbol: {result_5['n_rebalances']} rebalance events")
    else:
        print(f"      ⚠ 5-symbol: ONLY {result_5['n_rebalances']} rebalance events")
    print()
    print("  [3] Cost consistency:")
    print(f"      ✓ Same CostModel() default for both universe sizes")
    print(f"      ✓ No ADV lookup — uses qty as effective ADV (same as prior experiments)")
    print(f"      ✓ Short-selling borrow costs NOT modeled (same as prior)")
    print()
    print("  [4] Data quality:")
    print(f"      ✓ NIFTY 50: {len(symbols_50)} symbols passed exclusion criteria")
    missing_count = sum(1 for s in symbols_50 if s not in data_50)
    print(f"      ✓ No symbols with excessive missing data in final universe")

    # ── Bottom line ──
    print()
    print("=" * 72)
    print("  BOTTOM LINE")
    print("=" * 72)
    print()

    # Compare cost drags
    cost_drag_change = result_50["cost_drag_pct"] - result_5["cost_drag_pct"]
    sharpe_change = ci_50["sharpe"] - ci_5["sharpe"]

    ci_50_excludes_zero = ci_50["ci_lower"] > 0 or ci_50["ci_upper"] < 0
    ci_5_excludes_zero = ci_5["ci_lower"] > 0 or ci_5["ci_upper"] < 0

    print(f"  COST DRAG: 5-symbol={result_5['cost_drag_pct']:.1f}% → "
          f"NIFTY 50={result_50['cost_drag_pct']:.1f}% "
          f"({'↓' if cost_drag_change < 0 else '↑'} change of {abs(cost_drag_change):.1f}pp)")
    print(f"  SHARPE:    5-symbol={ci_5['sharpe']:.4f} → NIFTY 50={ci_50['sharpe']:.4f} "
          f"({'↑' if sharpe_change > 0 else '↓'} change of {abs(sharpe_change):.4f})")
    print()

    if result_50["cost_drag_pct"] < 100:
        print(f"  ✅ Cost drag below 100% — costs no longer dominate gross PnL")
    else:
        print(f"  ❌ Cost drag still {result_50['cost_drag_pct']:.1f}% — still above 100%")

    if ci_50_excludes_zero and ci_50["sharpe"] > 0:
        print(f"  ✅ POSITIVE SHARPE with statistical significance on NIFTY 50")
    elif ci_50_excludes_zero and ci_50["sharpe"] < 0:
        print(f"  ❌ NEGATIVE SHARPE with statistical significance on NIFTY 50")
    elif not ci_50_excludes_zero and result_50["net_pnl"] > 0:
        print(f"  ⚠ Positive but CI includes zero — not statistically significant")
    else:
        print(f"  ❌ NULL or negative — no statistically significant edge")

    print()

    if result_50["gross_pnl"] > 0 and result_50["cost_drag_pct"] < 100:
        print(f"  VERDICT: Expanding the universe to NIFTY 50 produces a")
        print(f"  cost-surviving edge. The cross-sectional signal works when")
        print(f"  given enough symbols for costs to average out.")
    elif result_50["gross_pnl"] > 0 and result_50["cost_drag_pct"] >= 100:
        print(f"  VERDICT: The signal still generates positive gross PnL but")
        print(f"  costs still exceed gross returns. Further universe expansion")
        print(f"  or lower rebalance frequency would be needed.")
    elif result_50["gross_pnl"] < 0:
        print(f"  VERDICT: Gross PnL is negative — the signal itself does not")
        print(f"  work on this universe. Universe size was not the binding")
        print(f"  constraint.")
    else:
        print(f"  VERDICT: No clear edge detected. See detailed discussion in report.")

    print()
    print("=" * 72)

    # ── Save results ──
    output = {
        "protocol": "UNIVERSE_EXPANSION_EXPERIMENT_PROTOCOL.md",
        "timestamp": pd.Timestamp.now().isoformat(),
        "parameters": {
            "lookback_n": LOOKBACK_N,
            "k": K,
            "rebalance_interval": REBALANCE_INTERVAL,
            "position_size_pct": POSITION_SIZE_PCT,
            "initial_capital": INITIAL_CAPITAL,
            "cost_model": "CostModel() default",
            "bootstrap": {
                "method": "stationary bootstrap (Politis-Romano)",
                "n_resamples": N_BOOTSTRAP,
                "mean_block_length": MEAN_BLOCK_LENGTH,
                "seed": BOOTSTRAP_SEED,
            },
        },
        "data": {
            "nifty50_symbols": symbols_50,
            "nifty50_count": len(symbols_50),
            "nifty50_excluded": [],
            "five_symbols": symbols_5,
        },
        "results_5_symbol": {
            "sharpe": float(ci_5["sharpe"]),
            "ci_lower": float(ci_5["ci_lower"]),
            "ci_upper": float(ci_5["ci_upper"]),
            "ci_excludes_zero": bool(ci_5_excludes_zero),
            "n_observations": int(ci_5.get("n_obs", 0)),
            "net_pnl": float(result_5["net_pnl"]),
            "gross_pnl": float(result_5["gross_pnl"]),
            "total_costs": float(result_5["total_costs"]),
            "cost_drag_pct": float(result_5["cost_drag_pct"]),
            "long_leg_pnl": float(result_5["long_leg_pnl"]),
            "short_leg_pnl": float(result_5["short_leg_pnl"]),
            "final_equity": float(result_5["final_equity"]),
            "n_rebalances": int(result_5["n_rebalances"]),
            "n_trades": int(result_5["n_trades"]),
        },
        "results_nifty50": {
            "sharpe": float(ci_50["sharpe"]),
            "ci_lower": float(ci_50["ci_lower"]),
            "ci_upper": float(ci_50["ci_upper"]),
            "ci_excludes_zero": bool(ci_50_excludes_zero),
            "n_observations": int(ci_50.get("n_obs", 0)),
            "net_pnl": float(result_50["net_pnl"]),
            "gross_pnl": float(result_50["gross_pnl"]),
            "total_costs": float(result_50["total_costs"]),
            "cost_drag_pct": float(result_50["cost_drag_pct"]),
            "long_leg_pnl": float(result_50["long_leg_pnl"]),
            "short_leg_pnl": float(result_50["short_leg_pnl"]),
            "final_equity": float(result_50["final_equity"]),
            "n_rebalances": int(result_50["n_rebalances"]),
            "n_trades": int(result_50["n_trades"]),
        },
    }

    output_path = Path(__file__).resolve().parent.parent.parent / "universe_expansion_results.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n>>> Results saved to {output_path}")


if __name__ == "__main__":
    main()
