from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from basket_backtest import monthly_rebalance_dates, simulate_rebalanced
from engines.cost_model import CostModel
from prices import point_in_time_adv


def _panel(n_days: int = 500, n_syms: int = 24, seed: int = 5):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2021-01-04", periods=n_days)
    syms = [f"T{i:02d}" for i in range(n_syms)]
    rets = rng.normal(0.0004, 0.015, size=(n_days, n_syms))
    closes = pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)), index=dates, columns=syms)
    opens = closes * (1 + rng.normal(0, 0.002, size=closes.shape))
    volumes = pd.DataFrame(rng.integers(100_000, 900_000, size=closes.shape).astype(float),
                           index=dates, columns=syms)
    return closes, opens, volumes


def _setup(closes, volumes):
    sched = monthly_rebalance_dates(closes, closes.index.max().date(), months_back=24)
    adv = point_in_time_adv(closes, volumes, sched)
    return [d for d in sched if adv[d]], adv


def _run(closes, opens, adv, sched, **kw):
    kw.setdefault("cost_model", CostModel())
    return simulate_rebalanced(closes, opens, adv, sched, **kw)


def test_invested_fraction_in_band_and_cash_nonnegative_after_every_rebalance():
    closes, opens, volumes = _panel()
    sched, adv = _setup(closes, volumes)
    res = _run(closes, opens, adv, sched)
    assert res["trace"]
    for row in res["trace"]:
        assert 0.99 <= row["invested_fraction"] <= 1.0
        assert row["cash"] >= -1e-6 * row["equity"]
        assert row["cash"] <= 0.01 * row["equity"]


def test_k_all_with_identical_inputs_gives_equal_weights_after_rebalance():
    closes, opens, volumes = _panel()
    sched, adv = _setup(closes, volumes)
    res = _run(closes, opens, adv, sched, k=len(closes.columns))
    for row in res["trace"]:
        vals = np.array(list(row["position_values"].values()))
        assert vals.max() - vals.min() <= 1e-6 * row["equity"]


def test_zero_cost_constant_price_world_keeps_equity_constant():
    closes, opens, volumes = _panel(n_days=300)
    closes[:] = 100.0
    opens[:] = 100.0
    sched, adv = _setup(closes, volumes)
    zero = CostModel(k_impact=0.0, brokerage_per_trade=0.0, stt_rate=0.0)
    res = _run(closes, opens, adv, sched, cost_model=zero, spread_bps=0.0)
    assert res["total_costs"] == 0.0
    assert all(abs(r) < 1e-12 for r in res["period_returns"])
    eqs = [row["equity"] for row in res["trace"]]
    assert max(eqs) - min(eqs) < 1e-6


def test_costs_scale_with_traded_notional():
    closes, opens, volumes = _panel()
    sched, adv = _setup(closes, volumes)
    spread_only = CostModel(k_impact=0.0, brokerage_per_trade=0.0, stt_rate=0.0)
    r10 = _run(closes, opens, adv, sched, cost_model=spread_only, spread_bps=10.0)
    r20 = _run(closes, opens, adv, sched, cost_model=spread_only, spread_bps=20.0)
    traded = sum(row["traded_notional"] for row in r10["trace"])
    traded20 = sum(row["traded_notional"] for row in r20["trace"])
    # Each run's costs equal the half-spread on its own traded notional (paths differ, so no ratio).
    assert r10["total_costs"] == pytest.approx(0.5 * 10.0 / 10_000.0 * traded, rel=1e-9)
    assert r20["total_costs"] == pytest.approx(0.5 * 20.0 / 10_000.0 * traded20, rel=1e-9)


def test_no_data_after_a_rebalance_affects_selection_or_adv_on_or_before_it():
    closes, opens, volumes = _panel()
    sched, adv = _setup(closes, volumes)
    cut = sched[len(sched) // 2]
    clean = _run(closes, opens, adv, sched)

    closes2, opens2, volumes2 = closes.copy(), opens.copy(), volumes.copy()
    late = closes2.index > pd.Timestamp(cut)
    closes2.loc[late] *= 3.0
    volumes2.loc[late] *= 50.0
    adv2 = point_in_time_adv(closes2, volumes2, sched)
    for d in sched:
        if d <= cut:
            assert adv2[d] == adv[d]
    dirty = _run(closes2, opens2, adv2, sched)
    before = [b for b in clean["baskets"] if b[0] <= cut]
    assert before == [b for b in dirty["baskets"] if b[0] <= cut]


def test_deterministic():
    closes, opens, volumes = _panel()
    sched, adv = _setup(closes, volumes)
    assert _run(closes, opens, adv, sched) == _run(closes, opens, adv, sched)


def test_held_name_without_open_on_execution_day_is_carried_not_traded():
    closes, opens, volumes = _panel()
    sched, adv = _setup(closes, volumes)
    base = _run(closes, opens, adv, sched)
    rb1, rb2 = base["trace"][0]["rebalance"], base["trace"][1]["rebalance"]
    exec1 = pd.Timestamp(base["trace"][0]["exec_day"])
    exec2 = pd.Timestamp(base["trace"][1]["exec_day"])
    name = next(s for s in base["trace"][0]["position_values"] if s in base["trace"][1]["position_values"])
    qty1 = base["trace"][0]["position_values"][name] / float(opens.at[exec1, name])

    opens2 = opens.copy()
    opens2.at[exec2, name] = np.nan
    res = _run(closes, opens2, adv, sched)
    assert {"rebalance": rb2, "symbol": name} in res["carried"]
    row2 = res["trace"][1]
    qty2 = row2["position_values"][name] / float(closes.loc[:exec2, name].iloc[-1])
    assert qty2 == pytest.approx(qty1, rel=1e-12)
    assert 0.99 <= row2["invested_fraction"] <= 1.0
