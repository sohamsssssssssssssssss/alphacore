"""Synthetic checks for momentum Amendments 1 and 3; no frozen data is read."""
import numpy as np
import pandas as pd
import pytest

from basket_backtest import simulate_rebalanced
from engines.cost_model import CostModel
from prices import point_in_time_adv


def panel():
    idx = pd.bdate_range("2020-01-01", periods=100)
    c = pd.DataFrame(100.0, index=idx, columns=list("ABC"))
    v = pd.DataFrame(200000.0, index=idx, columns=c.columns)
    return c, c.copy(), v, [idx[i].date() for i in (64, 75, 85)]


def simulate(c, o, v, sched, targets, **kw):
    history = point_in_time_adv(c, v, [d.date() for d in c.index])
    return simulate_rebalanced(c, o, {d: history[d] for d in sched}, sched,
                               select=lambda _, d, eligible: targets[sched.index(d)],
                               cost_model=CostModel(brokerage_per_trade=0), budget=1e7, spread_bps=30,
                               prior_close_carry=True, held_adv_history=history, **kw)


def test_held_sale_uses_most_recent_complete_session_adv_once_not_latest_month_end_or_future():
    c, o, v, sched = panel()
    c.iloc[70, 0] = np.nan
    v.iloc[69, 0] = 400000.0
    res = simulate(c, o, v, sched, [["A", "B"], ["B", "C"], ["B", "C"]])
    history = point_in_time_adv(c, v, [c.index[69].date()])
    assert res["input_uses"]["held_adv_fallback"] == [{
        "rebalance": sched[1].isoformat(), "symbol": "A", "source_date": c.index[69].date().isoformat(),
        "adv": history[c.index[69].date()]["A"]}]
    assert "A" not in res["trace"][1]["position_values"]


def test_unheld_target_without_open_removed_before_equal_sizing():
    c, o, v, sched = panel()
    o.iloc[65, 2] = np.nan
    res = simulate(c, o, v, sched, [["A", "B", "C"], ["A", "B"], ["A", "B"]])
    row = res["trace"][0]
    assert set(row["position_values"]) == {"A", "B"}
    assert row["position_values"]["A"] == pytest.approx(row["position_values"]["B"])
    assert res["input_uses"]["unheld_target_no_open"] == [{"rebalance": sched[0].isoformat(), "symbol": "C"}]
    assert 0.99 <= row["invested_fraction"] <= 1


@pytest.mark.parametrize("target_again", [False, True])
def test_nan_execution_carries_prior_close_unchanged_quantity_then_sells_or_resizes(target_again):
    c, o, v, sched = panel()
    o.iloc[76, 0] = np.nan
    c.iloc[74:77, 0] = np.nan
    # When resized later it must qualify again; supply a later third rebalance.
    if target_again:
        c = pd.concat([c, pd.DataFrame(100.0, index=pd.bdate_range(c.index[-1] + pd.Timedelta(days=1), periods=70), columns=c.columns)])
        o = o.reindex(c.index).fillna(100.0)
        o.iloc[76, 0] = np.nan
        v = v.reindex(c.index).fillna(200000.0)
        sched[-1] = c.index[150].date()
    targets = [["A", "B"], ["B", "C"], ["A", "B", "C"] if target_again else ["B", "C"]]
    res = simulate(c, o, v, sched, targets)
    first, second, third = res["trace"]
    assert second["position_values"]["A"] == pytest.approx(first["position_values"]["A"])
    assert second["position_values"]["B"] == pytest.approx(second["position_values"]["C"])
    uses = res["input_uses"]["held_no_open"]
    assert len(uses) == len(res["carried"]) == 1
    assert uses[0]["source_date"] == c.index[73].date().isoformat()
    assert uses[0]["price"] == 100.0
    assert res["input_uses"]["resumed_held_trades"] == [{
        "rebalance": sched[2].isoformat(), "symbol": "A", "action": "resized" if target_again else "sold"}]
    assert ("A" in third["position_values"]) == target_again


def test_carried_holdings_are_counted_as_invested_for_gate():
    c, o, v, sched = panel()
    o.iloc[76, 0] = np.nan
    checked = []
    res = simulate(c, o, v, sched, [["A", "B"], ["B", "C"], ["B", "C"]], check_rebalance=checked.append)
    row = checked[1]
    assert row["holdings_value"] == pytest.approx(sum(row["position_values"].values()))
    assert row["invested_fraction"] == pytest.approx(row["holdings_value"] / row["equity"])
    assert 0.99 <= row["invested_fraction"] <= 1
    assert res["input_uses"]["carried_invested"][0]["value"] == row["position_values"]["A"]


def test_month_end_without_later_session_is_skipped():
    c, o, v, sched = panel()
    sched.append(c.index[-1].date())
    res = simulate(c, o, v, sched, [["A", "B"]] * 4)
    assert res["skipped_rebalances"] == [sched[-1].isoformat()]
    assert res["n_rebalances"] == 3


def test_momentum_can_defer_all_returns_until_both_sides_pass_gates():
    c, o, v, sched = panel()
    res = simulate(c, o, v, sched, [["A", "B"]] * 3, compute_period_returns=False)
    assert len(res["trace"]) == 3
    assert res["period_returns"] == []
