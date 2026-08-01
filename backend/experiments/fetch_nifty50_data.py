#!/usr/bin/env python3.11
"""Fetch NIFTY 50 daily OHLCV data from yfinance for universe expansion experiment.

Saves each symbol as CSV in backend/data/nifty50_data/.

Exclusion criteria (pre-committed):
1. Must have >= 80% of expected trading days (min 850 of ~1239)
2. No more than 10 consecutive NaN days in Close
3. Must span at least 90% of the target range (2021-07-30 to 2026-07-30)
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data.nifty50_symbols import NIFTY50_SYMBOLS

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "nifty50_data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

TARGET_START = "2021-07-30"
TARGET_END = "2026-07-30"
MIN_ROWS = 850       # ~80% of 1239 expected trading days
MAX_CONSECUTIVE_NAN = 10
MIN_DATE_SPAN_PCT = 0.90  # must cover 90% of target date range

EXPECTED_TRADING_DAYS = 1239  # based on existing 5-symbol dataset


def main():
    print("=" * 72)
    print("  AlphaCore — Fetch NIFTY 50 Daily OHLCV Data")
    print("=" * 72)
    print(f"  Symbols: {len(NIFTY50_SYMBOLS)}")
    print(f"  Target range: {TARGET_START} to {TARGET_END}")
    print(f"  Output: {DATA_DIR}")
    print()

    tickers = [f"{sym}.NS" for sym in NIFTY50_SYMBOLS]

    # Download in batches to avoid rate limiting (yfinance is slow)
    BATCH_SIZE = 10
    all_data: dict[str, pd.DataFrame] = {}
    failures: list[str] = []
    excluded: dict[str, str] = {}

    print(">>> Downloading daily data from yfinance ...")

    for i in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[i:i + BATCH_SIZE]
        batch_symbols = NIFTY50_SYMBOLS[i:i + BATCH_SIZE]
        print(f"  Batch {i // BATCH_SIZE + 1}: {batch_symbols[0]} ... {batch_symbols[-1]}")

        try:
            data = yf.download(
                batch,
                start=TARGET_START,
                end=TARGET_END,
                auto_adjust=True,
                progress=False,
                threads=True,
            )
        except Exception as e:
            print(f"    ⚠ Batch failed: {type(e).__name__}: {str(e)[:80]}")
            # Fall back to individual downloads
            data = None

        if data is None or (isinstance(data, pd.DataFrame) and data.empty):
            # Try individual downloads
            for sym, ticker in zip(batch_symbols, batch):
                try:
                    df = yf.download(
                        ticker, start=TARGET_START, end=TARGET_END,
                        auto_adjust=True, progress=False,
                    )
                    if df is not None and len(df) > 0:
                        # MultiIndex case — single ticker returns single-level columns
                        if isinstance(df.columns, pd.MultiIndex):
                            df.columns = df.columns.droplevel(1)
                        all_data[sym] = df
                        print(f"    ✓ {sym}: {len(df)} rows")
                    else:
                        failures.append(sym)
                        print(f"    ✗ {sym}: empty data")
                except Exception as e2:
                    failures.append(sym)
                    print(f"    ✗ {sym}: {type(e2).__name__}: {str(e2)[:60]}")
                time.sleep(0.5)
            continue

        # Handle MultiIndex columns (batched download)
        if isinstance(data.columns, pd.MultiIndex):
            for sym in batch_symbols:
                ticker = f"{sym}.NS"
                try:
                    sym_data = data.xs(ticker, axis=1, level=0)
                    if len(sym_data) > 0:
                        all_data[sym] = sym_data
                        print(f"    ✓ {sym}: {len(sym_data)} rows")
                    else:
                        failures.append(sym)
                        print(f"    ✗ {sym}: empty after extraction")
                except (KeyError, ValueError):
                    # Fallback individual download
                    try:
                        df = yf.download(
                            f"{sym}.NS", start=TARGET_START, end=TARGET_END,
                            auto_adjust=True, progress=False,
                        )
                        if isinstance(df.columns, pd.MultiIndex):
                            df.columns = df.columns.droplevel(1)
                        if df is not None and len(df) > 0:
                            all_data[sym] = df
                            print(f"    ✓ {sym} (individual): {len(df)} rows")
                        else:
                            failures.append(sym)
                            print(f"    ✗ {sym}: empty fallback")
                    except Exception as e:
                        failures.append(sym)
                        print(f"    ✗ {sym}: {type(e).__name__}: {str(e)[:60]}")
                    time.sleep(0.5)
        else:
            print(f"    ⚠ Batch returned unexpected format — trying individual downloads")
            for sym, ticker in zip(batch_symbols, batch):
                try:
                    df = yf.download(
                        ticker, start=TARGET_START, end=TARGET_END,
                        auto_adjust=True, progress=False,
                    )
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.droplevel(1)
                    if df is not None and len(df) > 0:
                        all_data[sym] = df
                        print(f"    ✓ {sym}: {len(df)} rows")
                    else:
                        failures.append(sym)
                        print(f"    ✗ {sym}: empty")
                except Exception as e:
                    failures.append(sym)
                    print(f"    ✗ {sym}: {type(e).__name__}: {str(e)[:60]}")
                time.sleep(0.5)

        time.sleep(1.0)  # rate limiting between batches

    print(f"\n  Downloaded {len(all_data)} symbols successfully")
    print(f"  Failures: {len(failures)}" if failures else "  Failures: 0")

    # ── Apply exclusion criteria ──
    print("\n>>> Applying exclusion criteria ...")

    target_start_dt = pd.Timestamp(TARGET_START)
    target_end_dt = pd.Timestamp(TARGET_END)
    target_span_days = (target_end_dt - target_start_dt).days

    for sym in list(all_data.keys()):
        df = all_data[sym]
        df = df.sort_index()

        # Check 1: Row count
        n_rows = len(df)
        if n_rows < MIN_ROWS:
            excluded[sym] = f"Few rows: {n_rows} < {MIN_ROWS}"
            all_data.pop(sym)
            print(f"  ✗ {sym}: EXCLUDED — {excluded[sym]}")
            continue

        # Check 2: Consecutive NaNs in Close
        close_col = "Close" if "Close" in df.columns else "Adj Close"
        if close_col not in df.columns:
            excluded[sym] = f"No Close column"
            all_data.pop(sym)
            print(f"  ✗ {sym}: EXCLUDED — {excluded[sym]}")
            continue

        max_consecutive_nan = df[close_col].isna().astype(int).groupby(
            df[close_col].notna().astype(int).cumsum()
        ).transform("count").max()

        if max_consecutive_nan > MAX_CONSECUTIVE_NAN:
            excluded[sym] = f"Consecutive NaN: {int(max_consecutive_nan)} > {MAX_CONSECUTIVE_NAN}"
            all_data.pop(sym)
            print(f"  ✗ {sym}: EXCLUDED — {excluded[sym]}")
            continue

        # Check 3: Date span
        actual_start = df.index[0]
        actual_end = df.index[-1]
        actual_span = (actual_end - actual_start).days
        span_ratio = actual_span / target_span_days

        if span_ratio < MIN_DATE_SPAN_PCT:
            excluded[sym] = f"Date span: {actual_start.date()} to {actual_end.date()} ({span_ratio:.0%} of target)"
            all_data.pop(sym)
            print(f"  ✗ {sym}: EXCLUDED — {excluded[sym]}")
            continue

        print(f"  ✓ {sym}: {n_rows} rows, span={actual_start.date()} to {actual_end.date()}, "
              f"consec_nan={int(max_consecutive_nan)}")

    print(f"\n  Final universe: {len(all_data)} symbols")
    print(f"  Excluded: {len(excluded)} symbols")
    for sym, reason in excluded.items():
        print(f"    {sym}: {reason}")

    # ── Save to CSV ──
    print("\n>>> Saving to CSV ...")
    saved_symbols = []
    for sym, df in all_data.items():
        out_path = DATA_DIR / f"{sym}.csv"

        # Standardize format to match existing 5-symbol data
        df_out = df.reset_index()
        df_out = df_out.rename(columns={
            "index": "Date",
            "Date": "Date",
        })
        # Ensure Date column is first and properly formatted
        if "Date" not in df_out.columns:
            df_out.index.name = "Date"
            df_out = df_out.reset_index()

        # Keep only OHLCV columns
        keep_cols = ["Date", "Open", "High", "Low", "Close", "Volume"]
        existing_cols = [c for c in keep_cols if c in df_out.columns]
        df_out = df_out[existing_cols]
        df_out = df_out.sort_values("Date")

        df_out.to_csv(out_path, index=False)
        saved_symbols.append(sym)

    print(f"  Saved {len(saved_symbols)} symbol CSVs to {DATA_DIR}")

    # ── Save metadata ──
    metadata = {
        "tickers": [f"{sym}.NS" for sym in saved_symbols],
        "short_names": saved_symbols,
        "date_range": [str(all_data[sym].index[0].date()) if len(all_data[sym]) > 0 else "N/A"
                       for sym in saved_symbols],
        "total_rows": [len(all_data[sym]) for sym in saved_symbols],
        "n_symbols": len(saved_symbols),
        "n_excluded": len(excluded),
        "excluded": excluded,
        "source": f"yfinance auto_adjust=True",
        "pull_timestamp": pd.Timestamp.now().isoformat(),
    }

    meta_path = DATA_DIR / "metadata.json"
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2, default=str)
    print(f"  Metadata saved to {meta_path}")

    # ── Summary ──
    print()
    print("=" * 72)
    print("  SUMMARY")
    print("=" * 72)
    print(f"  Universe size: {len(saved_symbols)} / 50 NIFTY 50 symbols")
    print(f"  Excluded: {len(excluded)}")
    print(f"  Failures: {len(failures)}")
    print(f"  Date range: {TARGET_START} to {TARGET_END}")
    print(f"  Average rows per symbol: "
          f"{np.mean([len(all_data[sym]) for sym in saved_symbols]):.0f}")
    print()

    return saved_symbols


if __name__ == "__main__":
    main()
