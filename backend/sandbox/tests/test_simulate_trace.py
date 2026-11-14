from __future__ import annotations

import numpy as np
import pandas as pd

from basket_backtest import monthly_rebalance_dates, simulate
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


def test_trace_does_not_change_output_and_records_each_actionable_rebalance():
    closes, opens, volumes = _panel()
    sched = monthly_rebalance_dates(closes, closes.index.max().date(), months_back=24)
    adv = point_in_time_adv(closes, volumes, sched)
    plain = simulate(closes, {}, opens, sched, adv_by_date=adv)
    trace: list = []
    traced = simulate(closes, {}, opens, sched, adv_by_date=adv, trace=trace)
    assert plain == {k: v for k, v in traced.items()}  # same keys and values
    assert traced["period_returns"] == plain["period_returns"]
    assert len(trace) == len(traced["baskets"])
    last = trace[-1]
    assert abs(last["equity"] - traced["final_equity"]) < 1e-6
    assert abs(last["cash"] + last["holdings_value"] - last["equity"]) < 1e-6
    assert abs(sum(last["position_values"].values()) - last["holdings_value"]) < 1e-6
