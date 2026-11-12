from __future__ import annotations

import pytest

from costs import (
    BACKTEST_ASSUMED_COST_PARAMS,
    assumed_total_cost,
    cost_in_bps,
    extract_observed_fill,
    market_impact,
    observed_slippage_bps,
    spread_cost,
)

try:  # cross-check against the repo CostModel when running inside the repo
    from engines.cost_model import CostModel  # type: ignore

    REPO_COSTMODEL_AVAILABLE = True
except Exception:
    REPO_COSTMODEL_AVAILABLE = False


def test_assumed_buy_cost_is_impact_plus_spread_plus_brokerage():
    price, qty, adv = 2500.0, 100, 5e8
    expected = (
        market_impact(price, qty, adv)
        + spread_cost(price, qty)
        + BACKTEST_ASSUMED_COST_PARAMS["brokerage_per_trade_inr"]
    )
    assert assumed_total_cost(price, qty, adv, "BUY") == pytest.approx(expected)


def test_assumed_sell_cost_adds_stt():
    price, qty, adv = 2500.0, 100, 5e8
    buy = assumed_total_cost(price, qty, adv, "BUY")
    sell = assumed_total_cost(price, qty, adv, "SELL")
    stt = BACKTEST_ASSUMED_COST_PARAMS["stt_rate"] * price * qty
    assert sell == pytest.approx(buy + stt)


@pytest.mark.skipif(not REPO_COSTMODEL_AVAILABLE, reason="repo engines.cost_model not importable here")
def test_matches_repo_cost_model_defaults():
    from engines.cost_model import CostModel

    cm = CostModel()  # defaults: k_impact=0.0015, brokerage=20, stt=0.001
    price, qty, adv = 2480.5, 42, 3.2e9
    for side in ("BUY", "SELL"):
        repo = cm.total_cost(price=price, qty=qty, adv=adv, spread_bps=10.0, side=side)
        assert assumed_total_cost(price, qty, adv, side) == pytest.approx(repo)


def test_cost_in_bps():
    assert cost_in_bps(100.0, price=2500.0, qty=100) == pytest.approx(4.0)  # 100/250000*1e4


def test_observed_slippage_bps_buy_positive_when_overpaying():
    # Buying at 2510 vs ref 2500 => +40 bps adverse.
    assert observed_slippage_bps(2510.0, 2500.0, "BUY") == pytest.approx(40.0)
    # Selling at 2490 vs ref 2500 => +40 bps adverse (received less).
    assert observed_slippage_bps(2490.0, 2500.0, "SELL") == pytest.approx(40.0)


def test_extract_observed_fill_empty_response_returns_nones():
    out = extract_observed_fill({"status": "success", "data": {"order_id": "123"}})
    assert out["fill_price"] is None
    assert out["fill_qty"] is None


def test_extract_observed_fill_pulls_known_fields():
    out = extract_observed_fill({
        "status": "success",
        "data": {"order_id": "123", "average_price": "2510.00", "filled_quantity": "42",
                 "exchange_timestamp": "2026-08-31T15:30:00+05:30", "brokerage": "0"},
    })
    assert out["fill_price"] == pytest.approx(2510.0)
    assert out["fill_qty"] == pytest.approx(42.0)
    assert out["fill_timestamp"] == "2026-08-31T15:30:00+05:30"
    assert out["observed_fees_inr"] == pytest.approx(0.0)
