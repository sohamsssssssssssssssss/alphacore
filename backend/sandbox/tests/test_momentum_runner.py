from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import momentum_12_1 as mom
import momentum_runner as mr


def _panel(n_days: int, n_syms: int = 20, seed: int = 4):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2018-01-01", periods=n_days)
    syms = [f"N{i:02d}" for i in range(n_syms)]
    rets = rng.normal(0.0003, 0.012, size=(n_days, n_syms))
    closes = pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)), index=dates, columns=syms)
    opens = closes * (1 + rng.normal(0, 0.002, size=closes.shape))
    volumes = pd.DataFrame(2e5, index=dates, columns=syms)
    return closes, opens, volumes


def test_identical_selectors_give_exactly_zero_active_returns_and_outcome_no_evidence(monkeypatch):
    monkeypatch.setattr(mr, "GATE_MIN_ELIGIBLE", 5)
    closes, opens, volumes = _panel(n_days=700)
    sel, _, _ = mom.make_selectors(closes, volumes)
    res = mr.run(closes, opens, volumes, basket_select=sel, benchmark_select=sel)
    assert res["n_months"] > 10
    assert all(m["active"] == 0.0 for m in res["monthly"])
    assert res["ir"] == 0.0
    assert res["outcome"] == "No evidence of an edge"


def test_run_is_deterministic(monkeypatch):
    monkeypatch.setattr(mr, "GATE_MIN_ELIGIBLE", 5)
    closes, opens, volumes = _panel(n_days=700)
    a = mr.run(closes, opens, volumes)
    b = mr.run(closes, opens, volumes)
    assert a == b


def test_gate_aborts_before_returns_when_eligible_count_below_50():
    closes, opens, volumes = _panel(n_days=700, n_syms=20)  # 20 names < 50
    with pytest.raises(mr.AbortRun, match="eligible count"):
        mr.run(closes, opens, volumes)


def test_gate_skips_the_first_13_actionable_rebalances(monkeypatch):
    closes, opens, volumes = _panel(n_days=700, n_syms=20)
    monkeypatch.setattr(mr, "GATE_MIN_ELIGIBLE", 5)  # 20 names pass this lower bar
    res = mr.run(closes, opens, volumes)
    assert res["n_months"] > 0 and res["eligible_count_min"] >= 5
