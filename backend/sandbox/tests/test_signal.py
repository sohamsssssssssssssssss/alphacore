from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from rs_signal import (
    LOOKBACK_TRADING_DAYS,
    last_trading_day_of_month,
    previous_rebalance_date,
    rank_table,
    rebalance_dates,
    top_k,
    trailing_returns,
)


def make_closes(start: date, days: int, curves: dict[str, list[float]]) -> pd.DataFrame:
    """Build a closes DataFrame indexed by business days starting at `start`."""
    dates = pd.bdate_range(start=start, periods=days)
    df = pd.DataFrame({sym: pd.Series(vals, index=dates) for sym, vals in curves.items()})
    return df


def test_trailing_returns_window_is_21_days():
    start = date(2026, 1, 1)
    # Symbol A: 100 -> 110 over exactly 21 sessions => +10%; B: 100 -> 90 => -10%.
    days = 40
    a = [100.0] * (days - LOOKBACK_TRADING_DAYS) + [110.0] * LOOKBACK_TRADING_DAYS
    b = [100.0] * (days - LOOKBACK_TRADING_DAYS) + [90.0] * LOOKBACK_TRADING_DAYS
    closes = make_closes(start, days, {"A": a, "B": b})
    rets = trailing_returns(closes, as_of=date(2026, 2, 25))
    assert rets["A"] == pytest.approx(0.10)
    assert rets["B"] == pytest.approx(-0.10)


def test_top_k_selects_strongest_and_respects_k():
    start = date(2026, 1, 1)
    days = 40
    curves = {
        "A": [100.0] * 19 + [112.0] * 21,   # +12%
        "B": [100.0] * 19 + [105.0] * 21,   # +5%
        "C": [100.0] * 19 + [98.0] * 21,    # -2%
    }
    closes = make_closes(start, days, curves)
    as_of = date(2026, 2, 25)
    assert top_k(closes, as_of, k=1) == ["A"]
    assert top_k(closes, as_of, k=2) == ["A", "B"]


def test_no_lookahead_uses_only_data_through_as_of():
    start = date(2026, 1, 1)
    days = 45
    # A rockets up AFTER 2026-02-20; as of 2026-02-20 the signal must ignore it.
    base = [100.0] * 40 + [200.0] * 5
    flat = [100.0] * 45
    closes = make_closes(start, days, {"A": base, "B": flat})
    as_of = closes.index[39].date()  # before A's jump
    rets = trailing_returns(closes, as_of)
    assert rets["A"] == pytest.approx(0.0)
    tbl = rank_table(closes, as_of)
    assert tbl.index[0] == "A" or tbl.loc["A", "ret_21d"] == 0.0


def test_rank_table_marks_missing_data_last():
    start = date(2026, 1, 1)
    days = 40
    closes = make_closes(start, days, {"A": [100.0] * 40, "B": [50.0] * 5 + [np.nan] * 35})
    tbl = rank_table(closes, date(2026, 2, 25))
    assert not bool(tbl.loc["B", "has_data"])
    assert tbl["rank"].is_monotonic_increasing


def test_last_trading_day_of_month_uses_calendar():
    start = date(2026, 1, 1)
    closes = make_closes(start, 70, {"A": [100.0] * 70})
    # January 2026: last business day is Friday 2026-01-30.
    assert last_trading_day_of_month(closes, 2026, 1) == date(2026, 1, 30)
    # February 2026: last business day is Friday 2026-02-27.
    assert last_trading_day_of_month(closes, 2026, 2) == date(2026, 2, 27)


def test_rebalance_dates_are_last_trading_days_sorted_ascending():
    start = date(2025, 6, 2)
    closes = make_closes(start, 400, {"A": [100.0] * 400})
    dates = rebalance_dates(closes, end=date(2026, 8, 31), months_back=3)
    assert dates == sorted(dates)
    for d in dates:
        # Every rebalance date must be a day present in the trading calendar.
        assert pd.Timestamp(d) in closes.index


def test_previous_rebalance_date_strictly_prior():
    start = date(2025, 6, 2)
    closes = make_closes(start, 400, {"A": [100.0] * 400})
    prev = previous_rebalance_date(closes, as_of=date(2026, 8, 31))
    assert prev is not None and prev < date(2026, 8, 31)


def test_trailing_returns_respects_explicit_lookback():
    # Phase 2: parameterized lookback. A steps +10% exactly 25 sessions
    # before the end, so the 25-session window sees the jump while the
    # default 21-session window does not.
    start = date(2026, 1, 1)
    days = 50
    a = [100.0] * 25 + [110.0] * 25
    closes = make_closes(start, days, {"A": a})
    as_of = closes.index[-1].date()
    assert trailing_returns(closes, as_of, lookback=25)["A"] == pytest.approx(0.10)
    assert trailing_returns(closes, as_of, lookback=21)["A"] == pytest.approx(0.0)
    # Backward compatibility: default must equal the explicit 21.
    default = trailing_returns(closes, as_of)
    explicit = trailing_returns(closes, as_of, lookback=LOOKBACK_TRADING_DAYS)
    assert default.equals(explicit)


def test_trailing_returns_empty_below_lookback_plus_one():
    start = date(2026, 1, 1)
    closes = make_closes(start, 24, {"A": [100.0] * 24})
    rets = trailing_returns(closes, closes.index[-1].date(), lookback=25)
    assert rets.isna().all()  # 24 sessions < 26 needed for lookback=25


def test_rank_table_and_top_k_accept_lookback():
    start = date(2026, 1, 1)
    days = 50
    curves = {
        "A": [100.0] * 25 + [110.0] * 25,  # +10% at lookback=25, 0% at 21
        "B": [100.0] * 29 + [105.0] * 21,  # +5% at 21 (strong only in the recent window)
    }
    closes = make_closes(start, days, curves)
    as_of = closes.index[-1].date()
    # A leads the 25-session ranking but loses the 21-session ranking.
    assert top_k(closes, as_of, k=1, lookback=25) == ["A"]
    assert top_k(closes, as_of, k=1, lookback=21) == ["B"]
    assert rank_table(closes, as_of, lookback=25).index[0] == "A"
