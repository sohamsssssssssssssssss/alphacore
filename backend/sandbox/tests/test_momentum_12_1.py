from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import momentum_12_1 as mom
from basket_backtest import monthly_rebalance_dates, simulate_rebalanced
from engines.cost_model import CostModel
from prices import point_in_time_adv

N = 400  # sessions; enough for the 253-session window and 63-session ADV


def _panel(n_syms: int = 20, seed: int = 9):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2019-01-01", periods=N)
    syms = [f"M{i:02d}" for i in range(n_syms)]
    rets = rng.normal(0.0, 0.01, size=(N, n_syms))
    closes = pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)), index=dates, columns=syms)
    opens = closes * (1 + rng.normal(0, 0.002, size=closes.shape))
    volumes = pd.DataFrame(2e5, index=dates, columns=syms)  # 100 * 2e5 = 2e7 >= 1e7
    return closes, opens, volumes


def _rb(closes, pos=300):
    return closes.index[pos].date()


def test_signal_ignores_last_21_sessions_and_anything_after_d():
    closes, _, _ = _panel()
    d = _rb(closes)
    pos = closes.index.get_loc(pd.Timestamp(d))
    base = mom.signal(closes, d)
    touched = closes.copy()
    touched.iloc[pos - 20: pos + 1] *= 5.0  # last 21 sessions, including d
    touched.iloc[pos + 1:] *= 0.1  # the future
    assert mom.signal(touched, d).equals(base)
    # the 12-1 value is the close 21 sessions back over the close 252 sessions back
    s = closes.columns[0]
    assert base[s] == pytest.approx(closes[s].iloc[pos - 21] / closes[s].iloc[pos - 252] - 1.0)


def test_planted_12_month_winner_with_bad_last_month_is_selected():
    closes, opens, volumes = _panel()
    d = _rb(closes)
    pos = closes.index.get_loc(pd.Timestamp(d))
    w = "M00"
    # Strong rise over the 12 months up to t-21, then a 50% fall over the last month.
    ramp = np.linspace(100.0, 250.0, 252 - 21 + 1)  # index pos-252 .. pos-21
    closes.loc[closes.index[pos - 252: pos - 21 + 1], w] = ramp
    closes.loc[closes.index[pos - 20: pos + 1], w] = np.linspace(250.0, 125.0, 21)
    bsel, _, _ = mom.make_selectors(closes, volumes)
    elig, _ = mom.eligibility(closes, volumes, d)
    assert w in elig
    basket = bsel(closes, d, set(closes.columns))
    assert w in basket and basket[0] == w


@pytest.mark.parametrize("rule,mutate", [
    ("closes_complete_253", lambda c, v, pos: c.iloc.__setitem__((pos - 100, c.columns.get_loc("M05")), np.nan)),
    ("adv_63_ge_10m", lambda c, v, pos: v.iloc.__setitem__((slice(None), v.columns.get_loc("M05")), 1e4)),
    ("no_move_over_40pct", lambda c, v, pos: c.iloc.__setitem__((pos - 50, c.columns.get_loc("M05")),
                                                               c["M05"].iloc[pos - 51] * 1.5)),
])
def test_each_eligibility_rule_excludes_exactly_the_planted_violator(rule, mutate):
    closes, _, volumes = _panel()
    d = _rb(closes)
    pos = closes.index.get_loc(pd.Timestamp(d))
    closes, volumes = closes.copy(), volumes.copy()
    mutate(closes, volumes, pos)
    elig, counts = mom.eligibility(closes, volumes, d)
    assert "M05" not in elig
    assert set(closes.columns) - elig == {"M05"}
    assert counts["failed"][rule] == 1
    for other in mom.RULES:
        if other != rule:
            assert counts["failed"][other] == 0


def test_name_with_one_nan_close_in_window_is_excluded():
    closes, _, volumes = _panel()
    d = _rb(closes)
    pos = closes.index.get_loc(pd.Timestamp(d))
    closes = closes.copy()
    closes.iloc[pos - 200, closes.columns.get_loc("M03")] = np.nan
    elig, _ = mom.eligibility(closes, volumes, d)
    assert "M03" not in elig


def test_basket_is_top_fifth_of_eligible_and_benchmark_is_all_eligible():
    closes, _, volumes = _panel(n_syms=20)
    d = _rb(closes)
    bsel, mkt, info = mom.make_selectors(closes, volumes)
    eligible = set(closes.columns)
    basket = bsel(closes, d, eligible)
    bench = mkt(closes, d, eligible)
    assert len(basket) == len(bench) // 5
    assert set(bench) == info(d)["eligible_set"] and set(basket) <= set(bench)
    sig = mom.signal(closes, d)
    assert all(sig[basket[i]] >= sig[basket[i + 1]] for i in range(len(basket) - 1))


def _run(closes, opens, volumes, sched, bsel, mkt):
    adv = point_in_time_adv(closes, volumes, sched)
    sched = [x for x in sched if adv[x]]
    cm = CostModel(brokerage_per_trade=0.0)
    kw = dict(cost_model=cm, budget=1e7, spread_bps=30.0, lookback=21)
    b_tr, m_tr = [], []
    b = simulate_rebalanced(closes, opens, adv, sched, select=bsel, trace=b_tr, **kw)
    m = simulate_rebalanced(closes, opens, adv, sched, select=mkt, trace=m_tr, **kw)
    return b, m, b_tr, m_tr


def test_invested_fraction_in_band_and_cash_nonnegative_for_basket_and_benchmark():
    closes, opens, volumes = _panel()
    sched = monthly_rebalance_dates(closes, closes.index.max().date(), months_back=20)
    bsel, mkt, _ = mom.make_selectors(closes, volumes)
    _, _, bt, mt = _run(closes, opens, volumes, sched, bsel, mkt)
    assert bt and mt
    for row in bt + mt:
        assert 0.99 <= row["invested_fraction"] <= 1.0
        assert row["cash"] >= -1e-6 * row["equity"]


def test_identical_basket_and_benchmark_give_exactly_zero_active_returns():
    closes, opens, volumes = _panel()
    sched = monthly_rebalance_dates(closes, closes.index.max().date(), months_back=20)
    _, mkt, _ = mom.make_selectors(closes, volumes)
    b, m, _, _ = _run(closes, opens, volumes, sched, mkt, mkt)
    assert b["period_returns"] == m["period_returns"]
    assert all(x - y == 0.0 for x, y in zip(b["period_returns"], m["period_returns"]))


def test_deterministic():
    closes, opens, volumes = _panel()
    sched = monthly_rebalance_dates(closes, closes.index.max().date(), months_back=20)
    bsel, mkt, _ = mom.make_selectors(closes, volumes)
    a = _run(closes, opens, volumes, sched, bsel, mkt)[0]
    b = _run(closes, opens, volumes, sched, bsel, mkt)[0]
    assert a == b
