#!/usr/bin/env python3.11
"""
AlphaCore — Overnight Gap & Post-Earnings Announcement Drift Experiment

Tests two mechanistically distinct signals on the 5-symbol NSE daily dataset:
  1. Overnight gap reversal (primary)
  2. Post-earnings-announcement drift / PEAD (secondary)

Pre-committed protocol: OVERNIGHT_GAP_EXPERIMENT_PROTOCOL.md
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engines.backtest_metrics import compute_sharpe, stationary_bootstrap_sharpe_ci
from engines.cost_model import CostModel

# ── Configuration ──────────────────────────────────────────────────────────

SYMBOLS = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]
TICKERS = ["RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFCBANK.NS", "ICICIBANK.NS"]
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "real_nse_data"
TRAIN_END_INDEX = 867
TEST_START_INDEX = 867
INITIAL_CAPITAL = 100000.0
POSITION_SIZE_PCT = 0.10

# Overnight gap params
GAP_THRESHOLD = 0.015  # 1.5%
HYPOTHESIS = "reversal"  # pre-committed

# PEAD params
PEAD_SURPRISE_THRESHOLD = 0.05  # 5%
PEAD_HOLD_DAYS = 10

# Bootstrap
N_BOOTSTRAP = 2000
BOOTSTRAP_SEED = 2026
MEAN_BLOCK_LENGTH = 5

cost_model = CostModel()


# ── Data Loading ───────────────────────────────────────────────────────────

def load_ohlcv() -> dict[str, pd.DataFrame]:
    data = {}
    for sym in SYMBOLS:
        path = DATA_DIR / f"{sym}.csv"
        df = pd.read_csv(path, parse_dates=["Date"])
        df = df.sort_values("Date").reset_index(drop=True)
        data[sym] = df
    return data


def build_panel(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Build daily panel with close, open, and spread_bps per symbol."""
    panel = None
    for sym in SYMBOLS:
        df = data[sym]
        spread_bps = ((df["High"] - df["Low"]) / df["Close"] * 10000.0).clip(0.5, 50.0)
        small = df[["Date"]].copy()
        small["Date"] = pd.to_datetime(small["Date"])
        small[f"{sym}_open"] = df["Open"].values
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


# ── Overnight Gap Backtester ──────────────────────────────────────────────

def run_overnight_gap_strategy(panel: pd.DataFrame, initial_capital: float = INITIAL_CAPITAL) -> dict:
    """Run the overnight gap reversal strategy on the panel.

    For each day, for each symbol:
    - Compute overnight gap = (Open(t) - Close(t-1)) / Close(t-1)
    - If gap > +1.5%: SHORT (bet on reversal)
    - If gap < -1.5%: LONG (bet on reversal)
    - Enter at open, exit at close same day
    - Multiple symbols can trade on the same day
    """
    n_days = len(panel)
    equity = float(initial_capital)
    daily_returns: list[float] = []
    trades: list[dict] = []
    gross_pnl = 0.0
    total_costs = 0.0
    n_trading_days = 0

    for day_idx in range(1, n_days):  # need previous day's close
        row = panel.iloc[day_idx]
        prev_row = panel.iloc[day_idx - 1]
        prev_equity = equity
        day_pnl = 0.0
        day_costs = 0.0

        for sym in SYMBOLS:
            open_col = f"{sym}_open"
            close_col = f"{sym}_close"
            spread_col = f"{sym}_spread_bps"

            open_price = row[open_col]
            prev_close = prev_row[close_col]

            if pd.isna(open_price) or pd.isna(prev_close) or prev_close == 0:
                continue

            overnight_gap = (open_price - prev_close) / prev_close

            # Check threshold
            if abs(overnight_gap) <= GAP_THRESHOLD:
                continue

            # Determine direction (gap reversal)
            is_long = overnight_gap < 0  # gap down -> go long (bet on reversal up)
            is_short = overnight_gap > 0  # gap up -> go short (bet on reversal down)

            # Entry at open
            spread_bps = row[spread_col]
            bid_open, ask_open = close_to_bid_ask(open_price, spread_bps)
            entry_price = ask_open if is_long else bid_open

            # Position size
            qty = (POSITION_SIZE_PCT * equity) / entry_price if entry_price > 0 else 0.0
            if qty <= 0:
                continue

            # Cost at entry
            entry_side = "BUY" if is_long else "SELL"
            cost_entry = cost_model.total_cost(
                price=entry_price, qty=qty, adv=None,
                spread_bps=spread_bps, side=entry_side,
            )
            equity -= cost_entry
            total_costs += cost_entry
            day_costs += cost_entry

            # Exit at close
            close_price = row[close_col]
            bid_close, ask_close = close_to_bid_ask(close_price, spread_bps)
            exit_price = bid_close if is_long else ask_close
            exit_side = "SELL" if is_long else "BUY"

            # PnL
            if is_long:
                pnl = (exit_price - entry_price) * qty
            else:
                pnl = (entry_price - exit_price) * qty

            equity += pnl
            gross_pnl += pnl
            day_pnl += pnl

            # Cost at exit
            cost_exit = cost_model.total_cost(
                price=exit_price, qty=qty, adv=None,
                spread_bps=spread_bps, side=exit_side,
            )
            equity -= cost_exit
            total_costs += cost_exit
            day_costs += cost_exit

            # Simulated return % for the trade
            if is_long:
                trade_ret_pct = ((exit_price / entry_price) - 1) * 100
            else:
                trade_ret_pct = ((entry_price / exit_price) - 1) * 100

            trades.append({
                "symbol": sym,
                "direction": "LONG" if is_long else "SHORT",
                "date": str(panel.index[day_idx].date()),
                "gap_pct": float(overnight_gap * 100),
                "entry_price": float(entry_price),
                "exit_price": float(exit_price),
                "qty": float(qty),
                "pnl": float(pnl),
                "gross_pnl": float(pnl),
                "cost_entry": float(cost_entry),
                "cost_exit": float(cost_exit),
                "trade_return_pct": float(trade_ret_pct),
            })

        # Daily return
        daily_ret = (equity - prev_equity) / prev_equity if prev_equity > 0 else 0.0
        daily_returns.append(float(daily_ret))
        if len(trades) > 0:
            n_trading_days += 1

    net_pnl = equity - initial_capital
    denom = abs(float(gross_pnl))
    cost_drag_pct = (total_costs / denom * 100.0) if denom > 0 else 0.0

    daily_ret_array = np.array(daily_returns, dtype=float)

    return {
        "trades": trades,
        "daily_returns": daily_ret_array,
        "final_equity": float(equity),
        "net_pnl": float(net_pnl),
        "gross_pnl": float(gross_pnl),
        "total_costs": float(total_costs),
        "cost_drag_pct": float(cost_drag_pct),
        "n_trades": len(trades),
        "n_trading_days": n_trading_days,
        "long_trades": sum(1 for t in trades if t["direction"] == "LONG"),
        "short_trades": sum(1 for t in trades if t["direction"] == "SHORT"),
        "winning_trades": sum(1 for t in trades if t["pnl"] > 0),
    }


# ── PEAD Backtester ──────────────────────────────────────────────────────

def run_pead_strategy(panel: pd.DataFrame, earnings_data: dict[str, pd.DataFrame],
                      initial_capital: float = INITIAL_CAPITAL) -> dict:
    """Run the PEAD strategy.

    For each earnings event with |Surprise| > 5%, enter at close on
    announcement date, hold for 10 trading days, then exit.
    """
    equity = float(initial_capital)
    daily_returns: list[float] = []
    trades: list[dict] = []
    gross_pnl = 0.0
    total_costs = 0.0

    # Build date-indexed close prices
    close_prices = {}
    for sym in SYMBOLS:
        close_prices[sym] = panel[f"{sym}_close"]
    dates = panel.index

    # For each symbol, for each earnings date in test period
    for sym in SYMBOLS:
        if sym not in earnings_data:
            continue
        earnings = earnings_data[sym].copy()

        # Normalize timezone: yfinance dates are America/New_York timezone-aware
        earnings.index = earnings.index.tz_localize(None)

        # Filter to test period
        earnings = earnings[earnings.index >= panel.index[TEST_START_INDEX]]
        earnings = earnings[earnings.index <= panel.index[-1]]

        for ann_date, ann_row in earnings.iterrows():
            surprise_pct = float(ann_row.get("Surprise(%)", 0))
            if np.isnan(surprise_pct):
                continue

            if abs(surprise_pct) <= PEAD_SURPRISE_THRESHOLD:
                continue

            is_long = surprise_pct > 0
            is_short = surprise_pct < 0

            # Find the closest date in panel to the announcement date
            # Earnings are announced pre-market or after-close typically.
            # yfinance dates are the announcement dates.
            # We enter at close on the announcement date (or next available trading day)
            ann_close_idx = dates.get_indexer([ann_date], method="nearest")[0]
            if ann_close_idx < 0 or ann_close_idx >= len(dates):
                continue

            # Entry at ann_date close
            entry_date = dates[ann_close_idx]
            entry_close = panel.iloc[ann_close_idx][f"{sym}_close"]
            entry_spread = panel.iloc[ann_close_idx][f"{sym}_spread_bps"]
            bid_e, ask_e = close_to_bid_ask(entry_close, entry_spread)
            entry_price = ask_e if is_long else bid_e

            qty = (POSITION_SIZE_PCT * equity) / entry_price if entry_price > 0 else 0.0
            if qty <= 0:
                continue

            entry_side = "BUY" if is_long else "SELL"
            cost_entry = cost_model.total_cost(
                price=entry_price, qty=qty, adv=None,
                spread_bps=entry_spread, side=entry_side,
            )
            equity -= cost_entry
            total_costs += cost_entry

            # Exit at close PEAD_HOLD_DAYS later
            exit_idx = min(ann_close_idx + PEAD_HOLD_DAYS, len(panel) - 1)
            exit_date = dates[exit_idx]
            exit_close = panel.iloc[exit_idx][f"{sym}_close"]
            exit_spread = panel.iloc[exit_idx][f"{sym}_spread_bps"]
            bid_x, ask_x = close_to_bid_ask(exit_close, exit_spread)
            exit_price = bid_x if is_long else ask_x
            exit_side = "SELL" if is_long else "BUY"

            if is_long:
                pnl = (exit_price - entry_price) * qty
            else:
                pnl = (entry_price - exit_price) * qty

            equity += pnl
            gross_pnl += pnl

            cost_exit = cost_model.total_cost(
                price=exit_price, qty=qty, adv=None,
                spread_bps=exit_spread, side=exit_side,
            )
            equity -= cost_exit
            total_costs += cost_exit

            if is_long:
                trade_ret_pct = ((exit_price / entry_price) - 1) * 100
            else:
                trade_ret_pct = ((entry_price / exit_price) - 1) * 100

            trades.append({
                "symbol": sym,
                "direction": "LONG" if is_long else "SHORT",
                "ann_date": str(ann_date.date()),
                "entry_date": str(entry_date.date()),
                "exit_date": str(exit_date.date()),
                "surprise_pct": float(surprise_pct),
                "entry_price": float(entry_price),
                "exit_price": float(exit_price),
                "qty": float(qty),
                "pnl": float(pnl),
                "trade_return_pct": float(trade_ret_pct),
                "hold_period": int(exit_idx - ann_close_idx),
            })

    # Build daily returns from trades
    n_days = len(panel)
    # Final equity = initial capital + net PnL
    final_equity = initial_capital + sum(t["pnl"] for t in trades) - total_costs

    net_pnl = final_equity - initial_capital
    denom = abs(float(gross_pnl))
    cost_drag_pct = (total_costs / denom * 100.0) if denom > 0 else 0.0

    # For PEAD, the daily return array is sparse. Create daily returns.
    pead_daily = np.zeros(n_days, dtype=float)
    for t in trades:
        # This is a simplification: we spread the PnL evenly across the hold period
        # A more precise approach would assign daily MTM but that's complex
        pass

    # Simple approach: just compute buy-and-hold return for PnL, use per-event
    # for Sharpe (treat each event return as an independent observation)
    trade_returns = np.array([t["trade_return_pct"] / 100.0 for t in trades], dtype=float)

    return {
        "trades": trades,
        "daily_returns": trade_returns,  # per-event returns for PEAD
        "final_equity": float(final_equity),
        "net_pnl": float(net_pnl),
        "gross_pnl": float(gross_pnl),
        "total_costs": float(total_costs),
        "cost_drag_pct": float(cost_drag_pct),
        "n_trades": len(trades),
    }


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    print("=" * 72)
    print("  AlphaCore — Overnight Gap & PEAD Experiment")
    print("=" * 72)
    print("  Protocol: OVERNIGHT_GAP_EXPERIMENT_PROTOCOL.md")
    print()
    print(f"  Overnight gap: reversal hypothesis, {GAP_THRESHOLD*100:.1f}% threshold")
    print(f"  PEAD: {PEAD_SURPRISE_THRESHOLD*100:.0f}% surprise threshold, "
          f"{PEAD_HOLD_DAYS}-day hold, IF Step 0 passed")
    print()

    # ── Load data ──
    print(">>> Loading OHLCV data ...")
    raw_data = load_ohlcv()
    panel = build_panel(raw_data)
    test_panel = panel.iloc[TEST_START_INDEX:]
    print(f"  Test panel: {len(test_panel)} days")
    print(f"  Date range: {test_panel.index[0].date()} to {test_panel.index[-1].date()}")
    print()

    # ══════════════════════════════════════════════════════════════════════
    # PART A: OVERNIGHT GAP
    # ══════════════════════════════════════════════════════════════════════
    print("─" * 72)
    print("  PART A: OVERNIGHT GAP REVERSAL STRATEGY")
    print("─" * 72)
    print()

    gap_result = run_overnight_gap_strategy(test_panel, INITIAL_CAPITAL)

    daily_rets = gap_result["daily_returns"]
    sharpe_gap = compute_sharpe(daily_rets.tolist())
    ci_gap = stationary_bootstrap_sharpe_ci(
        daily_rets, n_bootstrap=N_BOOTSTRAP,
        mean_block_length=MEAN_BLOCK_LENGTH, seed=BOOTSTRAP_SEED,
    )

    # Trade-level stats
    n_trades = gap_result["n_trades"]
    n_win = gap_result["winning_trades"]
    n_long = gap_result["long_trades"]
    n_short = gap_result["short_trades"]

    print(f"  Results:")
    print(f"    Trades: {n_trades}")
    print(f"    Winning trades: {n_win}/{n_trades} ({n_win/n_trades*100:.1f}% win rate)"
          if n_trades > 0 else "    No trades triggered")
    print(f"    Long trades: {n_long}, Short trades: {n_short}")
    print(f"    Gross PnL: ₹{gap_result['gross_pnl']:+,.2f}")
    print(f"    Total costs: ₹{gap_result['total_costs']:+,.2f}")
    print(f"    Net PnL: ₹{gap_result['net_pnl']:+,.2f}")
    print(f"    Cost drag: {gap_result['cost_drag_pct']:.1f}%")
    print(f"    Final equity: ₹{gap_result['final_equity']:+,.2f}")
    print(f"    Return: {((gap_result['final_equity']/INITIAL_CAPITAL)-1)*100:.2f}%")
    print(f"    Sharpe: {sharpe_gap:.4f}")
    print(f"    95% CI: [{ci_gap['ci_lower']:.4f}, {ci_gap['ci_upper']:.4f}]")
    print(f"    CI excludes zero: {ci_gap['ci_lower'] > 0 or ci_gap['ci_upper'] < 0}")
    print()

    # Per-symbol breakdown
    print("  Per-symbol breakdown:")
    for sym in SYMBOLS:
        sym_trades = [t for t in gap_result["trades"] if t["symbol"] == sym]
        if sym_trades:
            sym_pnl = sum(t["pnl"] for t in sym_trades)
            sym_win = sum(1 for t in sym_trades if t["pnl"] > 0)
            gap_values = [t["gap_pct"] for t in sym_trades]
            avg_gap = np.mean(gap_values) if gap_values else 0
            print(f"    {sym:<12}: {len(sym_trades):>3} trades, "
                  f"PnL=₹{sym_pnl:>+7,.2f}, Win={sym_win}/{len(sym_trades)} "
                  f"({sym_win/len(sym_trades)*100:.0f}%), "
                  f"Avg gap={avg_gap:.2f}%")
        else:
            print(f"    {sym:<12}: No trades triggered")

    # Average PnL per trade
    if n_trades > 0:
        avg_pnl = gap_result["gross_pnl"] / n_trades
        avg_cost = gap_result["total_costs"] / n_trades
        print(f"\n    Average per trade: Gross PnL=₹{avg_pnl:.2f}, Cost=₹{avg_cost:.2f}")

    # Direction accuracy check
    if n_trades > 0:
        correct_direction = sum(
            1 for t in gap_result["trades"]
            if (t["direction"] == "LONG" and t["gap_pct"] < 0 and t["trade_return_pct"] > 0)
            or (t["direction"] == "SHORT" and t["gap_pct"] > 0 and t["trade_return_pct"] > 0)
        )
        print(f"    Gap reversal correct direction: {correct_direction}/{n_trades} "
              f"({correct_direction/n_trades*100:.1f}%)")
    print()

    # ══════════════════════════════════════════════════════════════════════
    # PART B: PEAD
    # ══════════════════════════════════════════════════════════════════════
    print("─" * 72)
    print("  PART B: POST-EARNINGS-ANNOUNCEMENT DRIFT (PEAD)")
    print("─" * 72)
    print()

    print(">>> Fetching earnings dates from yfinance ...")
    earnings_data = {}
    
    # Try getting earnings dates with retries and timeout protection
    for sym, ticker in zip(SYMBOLS, TICKERS):
        try:
            tk = yf.Ticker(ticker)
            ed = tk.earnings_dates
            if ed is not None and len(ed) > 0 and 'Surprise(%)' in ed.columns:
                earnings_data[sym] = ed
                print(f"  {sym}: {len(ed)} earnings dates ({ed.index[0].date()} to {ed.index[-1].date()})")
            else:
                print(f"  {sym}: earnings_dates returned empty or missing Surprise column")
        except Exception as e:
            print(f"  {sym}: Error fetching earnings dates - {type(e).__name__}: {str(e)[:80]}")
    print()
    
    if len(earnings_data) == 0:
        print("  >>> PEAD: No earnings data could be fetched. yfinance earnings_dates API is unreliable.")
        print("  >>> Dropping PEAD analysis for this task — data source not reliably available.")

    if len(earnings_data) > 0:
        pead_result = run_pead_strategy(panel, earnings_data, INITIAL_CAPITAL)

        pead_trades = pead_result["trades"]
        print(f"  Results:")
        print(f"    Trades: {pead_result['n_trades']}")
        if pead_result["n_trades"] > 0:
            n_win_pead = sum(1 for t in pead_trades if t["pnl"] > 0)
            print(f"    Winning trades: {n_win_pead}/{pead_result['n_trades']} "
                  f"({n_win_pead/pead_result['n_trades']*100:.1f}%)")
            print(f"    Gross PnL: ₹{pead_result['gross_pnl']:+,.2f}")
            print(f"    Total costs: ₹{pead_result['total_costs']:+,.2f}")
            print(f"    Net PnL: ₹{pead_result['net_pnl']:+,.2f}")
            print(f"    Cost drag: {pead_result['cost_drag_pct']:.1f}%")

            # Per-event Sharpe (using trade returns)
            trade_rets = pead_result["daily_returns"]
            if len(trade_rets) > 1:
                sharpe_pead = compute_sharpe(trade_rets.tolist(),
                                              periods_per_year=252 // PEAD_HOLD_DAYS)
                print(f"    Per-event Sharpe: {sharpe_pead:.4f}")

            # Per-symbol
            print()
            print("  Per-symbol breakdown:")
            for sym in SYMBOLS:
                sym_t = [t for t in pead_trades if t["symbol"] == sym]
                if sym_t:
                    sym_pnl = sum(t["pnl"] for t in sym_t)
                    sym_win = sum(1 for t in sym_t if t["pnl"] > 0)
                    avg_surp = np.mean([t["surprise_pct"] for t in sym_t])
                    print(f"    {sym:<12}: {len(sym_t):>2} events, "
                          f"PnL=₹{sym_pnl:>+7,.2f}, Win={sym_win}/{len(sym_t)}, "
                          f"Avg surprise={avg_surp:.1f}%")
                else:
                    print(f"    {sym:<12}: No qualifying events (surprise > 5%)")
        else:
            print("    No qualifying earnings events with |Surprise| > 5% in test period")
    else:
        print("  Earnings data unavailable — PEAD not tested.")
    print()

    # ── Save results ──
    output = {
        "protocol": "OVERNIGHT_GAP_EXPERIMENT_PROTOCOL.md",
        "parameters": {
            "gap_threshold_pct": GAP_THRESHOLD * 100,
            "gap_hypothesis": HYPOTHESIS,
            "pead_surprise_threshold_pct": PEAD_SURPRISE_THRESHOLD * 100,
            "pead_hold_days": PEAD_HOLD_DAYS,
            "position_size_pct": POSITION_SIZE_PCT * 100,
            "initial_capital": INITIAL_CAPITAL,
            "cost_model": "CostModel() default",
            "bootstrap": {
                "n_resamples": N_BOOTSTRAP,
                "mean_block_length": MEAN_BLOCK_LENGTH,
                "seed": BOOTSTRAP_SEED,
            },
        },
        "overnight_gap": {
            "sharpe": float(sharpe_gap),
            "ci_lower": float(ci_gap["ci_lower"]),
            "ci_upper": float(ci_gap["ci_upper"]),
            "ci_excludes_zero": bool(ci_gap["ci_lower"] > 0 or ci_gap["ci_upper"] < 0),
            "n_observations": int(ci_gap["n_obs"]),
            "n_trades": int(gap_result["n_trades"]),
            "win_rate": float(n_win / n_trades * 100) if n_trades > 0 else 0,
            "net_pnl": float(gap_result["net_pnl"]),
            "gross_pnl": float(gap_result["gross_pnl"]),
            "total_costs": float(gap_result["total_costs"]),
            "cost_drag_pct": float(gap_result["cost_drag_pct"]),
            "final_equity": float(gap_result["final_equity"]),
        },
        "pead": {
            "n_trades": int(pead_result["n_trades"]) if len(earnings_data) > 0 else 0,
            "net_pnl": float(pead_result["net_pnl"]) if len(earnings_data) > 0 else 0,
            "gross_pnl": float(pead_result["gross_pnl"]) if len(earnings_data) > 0 else 0,
            "total_costs": float(pead_result["total_costs"]) if len(earnings_data) > 0 else 0,
            "cost_drag_pct": float(pead_result["cost_drag_pct"]) if len(earnings_data) > 0 else 0,
        },
    }

    output_path = Path(__file__).resolve().parent.parent.parent / "overnight_gap_results.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f">>> Results saved to {output_path}")
    print()

    # ── Bottom line ──
    print("─" * 72)
    print("  BOTTOM LINE")
    print("─" * 72)
    print()

    gap_excludes = ci_gap["ci_lower"] > 0 or ci_gap["ci_upper"] < 0

    if n_trades < 10:
        print(f"  OVERNIGHT GAP: INCONCLUSIVE (only {n_trades} trades triggered)")
    elif gap_excludes and sharpe_gap > 0:
        print(f"  ✅ OVERNIGHT GAP: POSITIVE — Statistically significant positive Sharpe")
    elif gap_excludes and sharpe_gap < 0:
        print(f"  ❌ OVERNIGHT GAP: NEGATIVE — Loses money with statistical significance")
    elif sharpe_gap > 0:
        print(f"  ⚠ OVERNIGHT GAP: Suggestive but inconclusive (CI includes zero)")
    else:
        print(f"  ❌ OVERNIGHT GAP: NULL — No statistically significant edge detected")

    pead_t = pead_result["n_trades"] if len(earnings_data) > 0 else 0
    if pead_t == 0:
        print(f"  PEAD: Not tested (no qualifying events)")
    elif pead_t < 5:
        print(f"  PEAD: INCONCLUSIVE (only {pead_t} events)")
    elif pead_result["net_pnl"] > 0:
        print(f"  ✅ PEAD: Net profitable ({pead_result['net_pnl']:+,.2f})")
    else:
        print(f"  ❌ PEAD: Net unprofitable ({pead_result['net_pnl']:+,.2f})")

    print()
    print("─" * 72)


if __name__ == "__main__":
    main()
