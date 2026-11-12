"""
K=1 monthly cross-sectional relative strength signal (the -1.57 Sharpe config).

Module named `rs_signal` (not `signal`) to avoid the stdlib `signal` module
collision — stdlib signal is imported at interpreter startup and cached in
sys.modules, so `from signal import ...` would silently resolve to it.

Construction (per the research brief, confirmed with the user):
  * Universe: 49 symbols (Nifty 50 minus SBILIFE).
  * Lookback: trailing 21 trading-day (approx. one calendar month) return.
  * Cross-sectional rank: every rebalance, rank all 49 symbols by that
    return and hold ONLY the single highest-ranked symbol (K=1, top-1).
  * Rebalance schedule: on the LAST TRADING DAY of each month, using data
    strictly through that day's close (no lookahead).

No-lookahead guarantee: every computation filters the price history to
dates <= as_of before ranking. Orders derived from the as_of ranking are
executed AFTER that close (AMO / next-session open semantics), which is why
the harness logs the rebalance date and the execution timestamp separately.
"""

from __future__ import annotations

import calendar
from datetime import date

import numpy as np
import pandas as pd

LOOKBACK_TRADING_DAYS = 21


def trailing_returns(closes: pd.DataFrame, as_of: date, lookback: int = LOOKBACK_TRADING_DAYS) -> pd.Series:
    """
    Trailing `lookback`-session return for every symbol through `as_of`.

    Uses the last available trading day on/before as_of as the current close
    and the close exactly `lookback` sessions earlier. Defaults to
    LOOKBACK_TRADING_DAYS (21) so existing callers are unchanged.
    """
    df = closes[closes.index <= pd.Timestamp(as_of)]
    if len(df) < lookback + 1:
        return pd.Series(index=closes.columns, dtype=float)
    cur = df.iloc[-1]
    base = df.iloc[-1 - lookback]
    rets = (cur / base - 1.0).astype(float)
    # pandas 3.x removed mode.use_inf_as_na; replace infinities explicitly.
    rets = rets.replace([np.inf, -np.inf], np.nan)
    return rets


def rank_table(closes: pd.DataFrame, as_of: date, lookback: int = LOOKBACK_TRADING_DAYS) -> pd.DataFrame:
    """
    Full cross-sectional ranking as of `as_of`.

    Returns DataFrame indexed by symbol with columns:
      ret_21d, rank (1 = strongest), has_data.
    Symbols with missing/NaN returns are ranked last and flagged.
    """
    rets = trailing_returns(closes, as_of, lookback=lookback)
    out = rets.rename("ret_21d").to_frame()
    out["has_data"] = out["ret_21d"].notna()
    out = out.sort_values("ret_21d", ascending=False, na_position="last")
    out["rank"] = range(1, len(out) + 1)
    return out


def top_k(closes: pd.DataFrame, as_of: date, k: int = 1,
          lookback: int = LOOKBACK_TRADING_DAYS) -> list[str]:
    """Top-k symbols by trailing relative strength as of `as_of`."""
    tbl = rank_table(closes, as_of, lookback=lookback)
    ranked = [s for s in tbl.index if bool(tbl.loc[s, "has_data"])]
    return ranked[:k]


def last_trading_day_of_month(closes: pd.DataFrame, year: int, month: int) -> date | None:
    """Last trading day (from the closes calendar) in (year, month), or None."""
    _, last_day = calendar.monthrange(year, month)
    lo = pd.Timestamp(year=year, month=month, day=1)
    hi = pd.Timestamp(year=year, month=month, day=last_day, hour=23, minute=59)
    days = [d.date() for d in closes.index if lo <= d <= hi]
    return max(days) if days else None


def rebalance_dates(closes: pd.DataFrame, end: date, months_back: int = 6) -> list[date]:
    """
    Scheduled rebalance dates: the last trading day of each month within
    [end - months_back months, end], based on the closes trading calendar.
    """
    dates: list[date] = []
    y, m = end.year, end.month
    for _ in range(months_back + 1):
        d = last_trading_day_of_month(closes, y, m)
        if d is not None and d <= end:
            dates.append(d)
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return sorted(dates)


def previous_rebalance_date(closes: pd.DataFrame, as_of: date) -> date | None:
    """The scheduled rebalance date strictly before `as_of` (for rotation context)."""
    dates = rebalance_dates(closes, as_of, months_back=24)
    prior = [d for d in dates if d < as_of]
    return prior[-1] if prior else None
