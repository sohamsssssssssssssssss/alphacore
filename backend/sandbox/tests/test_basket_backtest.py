from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from basket_backtest import (
    compute_metrics,
    execution_day,
    quarterly_rebalance_dates,
    simulate,
    top_quartile,
)


def make_closes(start: date, days: int, curves: dict[str, list[float]]) -> pd.DataFrame:
    """Build a closes DataFrame indexed by business days starting at `start`."""
    dates = pd.bdate_range(start=start, periods=days)
    return pd.DataFrame({sym: pd.Series(vals, index=dates) for sym, vals in curves.items()})


def stepped_curve(dates: pd.DatetimeIndex, base: float, step_pct: float, step_dates: list[date]) -> list[float]:
    """Price that grows by `step_pct` on/after each step date (flat otherwise)."""
    return [base * (1.0 + step_pct) ** sum(1 for sd in step_dates if sd <= d.date()) for d in dates]


def test_top_quartile_selects_top_quarter_of_ranked_symbols():
    start = date(2024, 10, 1)
    days = 130
    curves: dict[str, list[float]] = {}
    for i in range(49):
        # Distinct 21-day trailing returns so ranking is unambiguous.
        curves[f"S{i + 1:02d}"] = [100.0] * (days - 21) + [100.0 * (1.0 + 0.001 * (i + 1))] * 21
    closes = make_closes(start, days, curves)
    as_of = closes.index[-1].date()  # last 21 sessions carry the step
    basket = top_quartile(closes, as_of)
    assert len(basket) == 12  # 49 // 4 = 12 (per the brief, "~12 out of 49")
    # The top-12 names must be the 12 highest-trailing-return symbols, in order.
    expected = [f"S{i + 1:02d}" for i in range(48, 36, -1)]
    assert basket == expected


def test_top_quartile_falls_back_when_few_symbols_have_data():
    start = date(2024, 10, 1)
    days = 130
    curves: dict[str, list[float]] = {}
    for i in range(3):  # only 3 symbols with data -> 3//4 = 0 -> at least 1
        curves[f"S{i + 1:02d}"] = [100.0] * (days - 21) + [100.0 * (1.0 + 0.01 * (i + 1))] * 21
    closes = make_closes(start, days, curves)
    as_of = closes.index[-1].date()
    assert top_quartile(closes, as_of) == ["S03"]


def test_quarterly_rebalance_dates_are_quarter_end_last_trading_days():
    start = date(2025, 6, 2)
    closes = make_closes(start, 400, {"A": [100.0] * 400})
    dates = quarterly_rebalance_dates(closes, end=date(2026, 8, 31))  # default quarters_back=24
    assert dates == sorted(dates)
    assert [d.month for d in dates] == [6, 9, 12, 3, 6]  # 2025-Q2,Q3,Q4 and 2026-Q1,Q2
    for d in dates:
        assert pd.Timestamp(d) in closes.index  # last trading day per the calendar


def test_quarterly_rebalance_dates_cover_full_window():
    # quarters_back=24 must span the full ~6y window (24 quarter-ends), not just
    # 25 months — regression test for the months-vs-quarters iteration bug.
    start = date(2020, 6, 1)
    closes = make_closes(start, 1600, {"A": [100.0] * 1600})
    dates = quarterly_rebalance_dates(closes, end=date(2026, 8, 31), quarters_back=24)
    assert len(dates) == 24  # 2020-Q3, Q4 (2) + 2021..2025 (20) + 2026-Q1, Q2 (2)
    assert dates[0] == date(2020, 9, 30)
    assert dates[-1] == date(2026, 6, 30)


def test_execution_day_is_next_session_strictly_after():
    start = date(2025, 6, 2)
    closes = make_closes(start, 30, {"A": [100.0] * 30})
    assert execution_day(closes, date(2025, 6, 6)) == date(2025, 6, 9)  # Fri -> Mon
    assert execution_day(closes, closes.index.max().date()) is None


def test_simulate_stable_basket_zero_turnover_and_exact_drift():
    """A basket that never changes should trade only at inception and earn the
    exact holding drift (equal-weight drift is exact when every holding moves
    by the same factor)."""
    start = date(2024, 10, 1)
    days = 200
    dates = pd.bdate_range(start=start, periods=days)
    rb1, rb2, rb3 = date(2025, 1, 31), date(2025, 2, 28), date(2025, 3, 31)
    curves: dict[str, list[float]] = {}
    # S1, S2 gain +2% per rebalance; S3..S8 flat. 8 symbols -> k = 2.
    curves["S1"] = stepped_curve(dates, 100.0, 0.02, [rb1, rb2, rb3])
    curves["S2"] = stepped_curve(dates, 95.0, 0.02, [rb1, rb2, rb3])
    for i in range(3, 9):
        curves[f"S{i}"] = [50.0] * days
    closes = make_closes(start, days, curves)
    opens = closes.copy()  # open == close for synthetic clarity
    adv = {s: 1e9 for s in curves}

    res = simulate(closes, adv, opens, [rb1, rb2, rb3], budget=1_000_000.0)
    assert res["k_used"] == 2
    assert res["n_rebalances"] == 3
    assert res["n_period_returns"] == 2
    assert sorted(res["baskets"][0][1]) == ["S1", "S2"]
    assert sorted(res["baskets"][1][1]) == ["S1", "S2"]
    assert sorted(res["baskets"][2][1]) == ["S1", "S2"]
    assert res["legs_per_period"] == [0, 0]  # no rotations after inception
    assert res["avg_legs_per_rebalance"] == 0.0
    assert res["avg_turnover_fraction"] == 0.0
    # Both holdings rise exactly 2% between fills -> ~2% net period returns
    # (no trades at rb2/rb3 means no costs; tiny residual from the uninvested
    # cash remainder, which is fixed between rebalances).
    assert res["period_returns"][0] == pytest.approx(0.02, abs=1e-4)
    assert res["period_returns"][1] == pytest.approx(0.02, abs=1e-4)
    # Win-alignment (beats equal-weight all-universe, gross): 2% vs ~0.5% -> both periods win.
    assert res["win_alignment_pct"] == pytest.approx(100.0)


def test_simulate_counts_delta_legs_and_turnover_on_rotation():
    """When one name drops out of the basket, only that delta is traded."""
    start = date(2024, 10, 1)
    days = 200
    dates = pd.bdate_range(start=start, periods=days)
    rb1, rb2, rb3 = date(2025, 1, 31), date(2025, 2, 28), date(2025, 3, 31)
    curves: dict[str, list[float]] = {}
    curves["S1"] = stepped_curve(dates, 100.0, 0.02, [rb1, rb2, rb3])   # stays top
    curves["S2"] = stepped_curve(dates, 95.0, 0.02, [rb1, rb2, rb3])   # top at rb1/rb2
    curves["S3"] = stepped_curve(dates, 50.0, 0.05, [rb3])             # jumps only at rb3
    for i in range(4, 9):
        curves[f"S{i}"] = [50.0] * days
    closes = make_closes(start, days, curves)
    opens = closes.copy()
    adv = {s: 1e9 for s in curves}

    res = simulate(closes, adv, opens, [rb1, rb2, rb3], budget=1_000_000.0)
    # rb3 basket: S3 (+5%) and S1 (+4.04%) beat S2 (+4.04% tie with S1 at rb3,
    # but S2 ranked below S3, so S3 enters and S2 exits).
    assert sorted(res["baskets"][0][1]) == ["S1", "S2"]
    assert sorted(res["baskets"][1][1]) == ["S1", "S2"]
    assert sorted(res["baskets"][2][1]) == ["S1", "S3"]
    assert res["legs_per_period"] == [0, 2]  # sell S2 + buy S3 at rb3
    assert res["avg_legs_per_rebalance"] == pytest.approx(1.0)  # (0 + 2) / 2 periods
    assert res["avg_turnover_fraction"] == pytest.approx((0.0 + 2 / 4.0) / 2)  # avg over both periods


def test_compute_metrics_reuses_repo_sharpe_and_bootstrap_ci():
    res = compute_metrics([0.01, 0.02, -0.005, 0.015, 0.03], periods_per_year=12)
    assert np.isfinite(res["sharpe"])
    assert res["ci_lower"] <= res["sharpe"] <= res["ci_upper"]
    assert res["ci_n_bootstrap"] == 1000
    assert res["ci_n_obs"] == 5


def test_simulate_skips_rebalances_without_data():
    start = date(2024, 10, 1)
    days = 200
    curves = {"A": [100.0] * days, "B": [90.0] * days}
    closes = make_closes(start, days, curves)
    opens = closes.copy()
    # Both rebalances are before any 21-session lookback is possible.
    early = [date(2024, 10, 10), date(2024, 10, 17)]
    with pytest.raises(RuntimeError):
        simulate(closes, {"A": 1e9, "B": 1e9}, opens, early, budget=1e6)


def test_top_quartile_respects_explicit_k():
    # Phase 2 sensitivity: k=10 / k=15 must select exactly that many names,
    # with the k=10 names a subset of the k=15 names. Default stays quartile.
    start = date(2024, 10, 1)
    days = 130
    curves: dict[str, list[float]] = {}
    for i in range(49):
        curves[f"S{i + 1:02d}"] = [100.0] * (days - 21) + [100.0 * (1.0 + 0.001 * (i + 1))] * 21
    closes = make_closes(start, days, curves)
    as_of = closes.index[-1].date()
    top10 = top_quartile(closes, as_of, k=10)
    top15 = top_quartile(closes, as_of, k=15)
    top12 = top_quartile(closes, as_of, k=12)
    assert len(top10) == 10
    assert len(top15) == 15
    assert len(top12) == 12
    assert len(top_quartile(closes, as_of)) == 12  # auto quartile unchanged
    assert set(top10).issubset(set(top15))
    assert set(top10).issubset(set(top12))


def test_top_quartile_respects_lookback():
    # A is +10% over the last 25 sessions but flat over the last 21: the
    # 25-session basket leads with A, the 21-session basket with B.
    start = date(2024, 10, 1)
    days = 50
    curves = {
        "A": [100.0] * 25 + [110.0] * 25,   # +10% at lookback=25, 0% at 21
        "B": [100.0] * 29 + [105.0] * 21,   # +5% at 21 (recent-window strength only)
    }
    closes = make_closes(start, days, curves)
    as_of = closes.index[-1].date()
    # 2 symbols -> auto quartile would be max(1, 2//4)=1; explicit lookback drives selection.
    assert top_quartile(closes, as_of, lookback=25) == ["A"]
    assert top_quartile(closes, as_of, lookback=21) == ["B"]


def test_simulate_respects_k_override():
    # Phase 2: --k overrides basket size in the simulation engine.
    start = date(2024, 10, 1)
    days = 200
    dates = pd.bdate_range(start=start, periods=days)
    rb1, rb2, rb3 = date(2025, 1, 31), date(2025, 2, 28), date(2025, 3, 31)
    curves: dict[str, list[float]] = {}
    curves["S1"] = stepped_curve(dates, 100.0, 0.02, [rb1, rb2, rb3])
    curves["S2"] = stepped_curve(dates, 95.0, 0.02, [rb1, rb2, rb3])
    for i in range(3, 9):
        curves[f"S{i}"] = [50.0] * days
    closes = make_closes(start, days, curves)
    opens = closes.copy()
    adv = {s: 1e9 for s in curves}
    # Default quartile on 8 symbols -> k=2 (see stable-basket test); k=1 forces top-1.
    res = simulate(closes, adv, opens, [rb1, rb2, rb3], budget=1_000_000.0, k=1)
    assert res["k_used"] == 1
    for rb, basket, size in res["baskets"]:
        assert sorted(basket) == ["S1"]
    assert res["legs_per_period"] == [0, 0]


def test_top_quartile_with_lookback_uses_parameterized_rank():
    # Explicit lookback must reach rs_signal.rank_table (not just selection).
    start = date(2024, 10, 1)
    days = 50
    curves = {
        "A": [100.0] * 25 + [110.0] * 25,   # +10% at lookback=25, 0% at 21
        "B": [100.0] * 29 + [105.0] * 21,   # +5% at 21 (recent-window strength only)
    }
    closes = make_closes(start, days, curves)
    as_of = closes.index[-1].date()
    assert top_quartile(closes, as_of, k=1, lookback=25) == ["A"]
    assert top_quartile(closes, as_of, k=1, lookback=21) == ["B"]
