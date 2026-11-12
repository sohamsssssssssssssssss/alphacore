"""
Task 1 — ADV window sanity check (2026-07-31 basket).

Computes per-symbol ADV (mean daily traded value = close*volume over the last
63 trading sessions, the repo's ADV_WINDOW_TRADING_DAYS) over two fetch
windows:
  * harness window:  ~730 calendar days  (prices.py FETCH_PERIOD_DAYS default)
  * backtest window: ~2190 calendar days (basket_backtest.py FETCH_PERIOD_DAYS)

Same symbols/adv computation as backend/sandbox/prices.py. Reports both ADV
values, the % difference, and flags any symbol whose ADV differs > 15%.
Read-only; no logic changes.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

SYMBOLS = ["HCLTECH", "DIVISLAB", "TECHM", "BAJAJ-AUTO", "TCS", "HEROMOTOCO",
           "BAJFINANCE", "BAJAJFINSV", "EICHERMOT", "TITAN", "INFY", "M&M"]
AS_OF = date(2026, 7, 31)
ADV_WINDOW_DAYS = 63


def yf_symbol(sym: str) -> str:
    return f"{sym}.NS"


def fetch_adv(symbols: list[str], fetch_period_days: int) -> dict[str, float]:
    """Mirror prices.py: fetch daily bars, ADV = mean(close*volume, last 63 sessions)."""
    end = AS_OF + timedelta(days=1)
    start = AS_OF - timedelta(days=fetch_period_days)
    adv: dict[str, float] = {}
    for sym in symbols:
        df = yf.download(yf_symbol(sym), start=start.isoformat(), end=end.isoformat(),
                         interval="1d", progress=False, auto_adjust=True)
        if df is None or df.empty:
            adv[sym] = float("nan")
            print(f"[DATA] {sym}: no data for window {fetch_period_days}d")
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        closes = df["Close"].dropna()
        volumes = df["Volume"].fillna(0.0)
        traded = (closes * volumes).tail(ADV_WINDOW_DAYS)
        adv[sym] = float(traded.mean()) if len(traded) else float("nan")
    return adv


def main() -> int:
    print(f"[RUN] ADV window sanity check, basket of {len(SYMBOLS)} symbols, "
          f"as_of={AS_OF}, ADV window = last {ADV_WINDOW_DAYS} trading sessions")
    adv_730 = fetch_adv(SYMBOLS, 730)
    adv_2190 = fetch_adv(SYMBOLS, 2190)

    print(f"\n{'symbol':<12}{'ADV_730d':>16}{'ADV_2190d':>16}{'diff %':>10}  flag")
    for sym in SYMBOLS:
        a, b = adv_730[sym], adv_2190[sym]
        if pd.isna(a) or pd.isna(b) or b == 0:
            print(f"{sym:<12}{a:>16,.0f}{b:>16,.0f}{'n/a':>10}  DATA-MISSING")
            continue
        diff = (a / b - 1.0) * 100.0
        flag = ">15% DIFF" if abs(diff) > 15.0 else "-"
        print(f"{sym:<12}{a:>16,.0f}{b:>16,.0f}{diff:>9.2f}%  {flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
