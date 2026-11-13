"""
Daily NSE price data for the sandbox harness.

Data source: yfinance daily bars (symbol.NS) — the same source the backtest
used for its "NSE daily bars". This is a READ-ONLY, best-effort fetch: every
per-symbol success/failure is logged, and missing symbols are dropped from
the ranking with a loud warning rather than silently imputed.

Upstox instrument keys are resolved separately in instruments.py (from
Upstox's published instrument master) — not here.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

YF_SUFFIX = ".NS"
BATCH_WORKERS = 4
FETCH_PERIOD_DAYS = 730  # ~2y of daily bars
ADV_WINDOW_TRADING_DAYS = 63


def yf_symbol(symbol: str) -> str:
    sym = symbol.upper()
    return sym if sym.endswith(YF_SUFFIX) else f"{sym}{YF_SUFFIX}"


def _download_one(symbol: str, start: str, end: str, include_open: bool = False) -> tuple[str, pd.DataFrame | None]:
    """Download daily bars for one symbol; returns (symbol, df_or_None)."""
    ticker = yf_symbol(symbol)
    try:
        df = yf.download(ticker, start=start, end=end, interval="1d", progress=False, auto_adjust=True)
    except Exception as exc:  # yfinance raises on network/parse issues
        logger.warning("yfinance download failed for %s: %s", ticker, exc)
        return symbol, None

    if df is None or df.empty:
        # TATAMOTORS-style fallback used elsewhere in AlphaCore: try BSE copy.
        alt = f"{symbol}.BO"
        try:
            df = yf.download(alt, start=start, end=end, interval="1d", progress=False, auto_adjust=True)
            if df is None or df.empty:
                return symbol, None
            logger.info("Fell back to %s for %s", alt, symbol)
        except Exception:
            return symbol, None

    # yfinance >=1.5 returns MultiIndex columns (Price/Ticker) even for a
    # single ticker; flatten so df["Close"] is a Series, not a DataFrame.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    closes = df["Close"].dropna()
    volumes = df["Volume"].fillna(0.0)
    if isinstance(closes, pd.Series) and len(closes) > 0:
        cols: dict[str, pd.Series] = {"close": closes, "volume": volumes}
        if include_open and "Open" in df.columns:
            opens = df["Open"].dropna()
            if isinstance(opens, pd.Series) and len(opens) > 0:
                cols["open"] = opens
        return symbol, pd.DataFrame(cols)
    return symbol, None


def fetch_daily_bars(symbols: list[str], as_of: date, months_back: int = 18,
                     fetch_period_days: int = FETCH_PERIOD_DAYS,
                     include_open: bool = False) -> tuple[pd.DataFrame, dict[str, float]] | tuple[pd.DataFrame, dict[str, float], pd.DataFrame]:
    """
    Fetch daily bars for all symbols through `as_of`.

    Args:
        symbols: universe to fetch.
        as_of: data cutoff date (only bars through this date are kept).
        months_back: retained for signature compatibility (unused; see
            fetch_period_days).
        fetch_period_days: calendar days of history to download (default 730).
        include_open: when True, also return a per-symbol DataFrame of daily
            open prices (next-session-open fills for backtests).

    Returns:
        closes: DataFrame indexed by trading date, one column per symbol (NaN where missing).
        adv_inr: dict symbol -> average daily traded value (close*volume, last 63 sessions).
        opens (only when include_open=True): DataFrame of open prices, same shape as closes.
    """
    end = as_of + timedelta(days=1)
    start = as_of - timedelta(days=fetch_period_days)

    results: dict[str, pd.DataFrame | None] = {}
    with ThreadPoolExecutor(max_workers=BATCH_WORKERS) as pool:
        futs = {pool.submit(_download_one, s, start.isoformat(), end.isoformat(), include_open): s for s in symbols}
        for fut in as_completed(futs):
            symbol = futs[fut]
            try:
                _, df = fut.result()
            except Exception as exc:
                logger.warning("fetch task failed for %s: %s", symbol, exc)
                df = None
            results[symbol] = df
            if df is None:
                print(f"[DATA] {symbol}: FAILED to fetch daily bars (dropped from ranking)")
            else:
                print(f"[DATA] {symbol}: {len(df)} daily bars through {df.index.max().date()}")

    frames = []
    for sym in symbols:
        df = results.get(sym)
        if df is None or df.empty:
            continue
        df = df.copy()
        renamed = []
        for c in df.columns:
            if c == "close":
                renamed.append(f"{sym}_close")
            elif c == "volume":
                renamed.append(f"{sym}_vol")
            elif c == "open":
                renamed.append(f"{sym}_open")
            else:
                renamed.append(c)
        df.columns = renamed
        frames.append(df)

    if not frames:
        raise RuntimeError("No price data fetched for any symbol — cannot compute signal.")

    merged = pd.concat(frames, axis=1).sort_index()
    merged = merged[merged.index <= pd.Timestamp(as_of)]

    close_cols = [c for c in merged.columns if c.endswith("_close")]
    closes = merged[close_cols].copy()
    closes.columns = [c.replace("_close", "") for c in close_cols]
    closes = closes.astype(float)

    adv: dict[str, float] = {}
    for sym in symbols:
        vol_col = f"{sym}_vol"
        if vol_col not in merged.columns:
            continue
        window = merged[[f"{sym}_close", vol_col]].tail(ADV_WINDOW_TRADING_DAYS)
        traded_value = (window[f"{sym}_close"] * window[vol_col]).mean()
        adv[sym] = float(traded_value) if pd.notna(traded_value) else 0.0

    if include_open:
        open_cols = [c for c in merged.columns if c.endswith("_open")]
        opens = merged[open_cols].copy() if open_cols else pd.DataFrame(index=merged.index)
        opens.columns = [c.replace("_open", "") for c in open_cols]
        opens = opens.astype(float)
        return closes, adv, opens

    return closes, adv


def now_utc_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
