from engines.cost_model import CostModel
import pytest


def test_market_impact_increases_with_qty():
    cm = CostModel()
    c_small = cm.market_impact(price=1000.0, qty=100.0, adv=1_000_000.0)
    c_big = cm.market_impact(price=1000.0, qty=1000.0, adv=1_000_000.0)
    assert c_big > c_small


def test_stt_only_applied_on_sell_side():
    cm = CostModel(k_impact=0.0, brokerage_per_trade=0.0, stt_rate=0.001)
    sell = cm.total_cost(price=1000.0, qty=10.0, adv=10_000.0, spread_bps=0.0, side="SELL")
    buy = cm.total_cost(price=1000.0, qty=10.0, adv=10_000.0, spread_bps=0.0, side="BUY")
    assert sell > buy
    assert abs(sell - buy - 10.0) < 1e-9


def test_zero_cost_when_qty_zero():
    cm = CostModel()
    assert cm.total_cost(price=1000.0, qty=0.0, adv=1_000_000.0, spread_bps=5.0, side="SELL") == 0.0


def test_total_cost_greater_than_brokerage_floor_for_positive_qty():
    cm = CostModel(brokerage_per_trade=20.0)
    total = cm.total_cost(price=1000.0, qty=100.0, adv=1_000_000.0, spread_bps=5.0, side="BUY")
    assert total > cm.brokerage_per_trade


@pytest.mark.parametrize("qty1,qty2", [(1, 2), (5, 10), (10, 20), (20, 40), (50, 100), (100, 200), (200, 400), (300, 600), (400, 800), (500, 1000)])
def test_total_cost_monotonic_with_qty(qty1, qty2):
    cm = CostModel()
    c1 = cm.total_cost(price=1000.0, qty=float(qty1), adv=1_000_000.0, spread_bps=5.0, side="BUY")
    c2 = cm.total_cost(price=1000.0, qty=float(qty2), adv=1_000_000.0, spread_bps=5.0, side="BUY")
    assert c2 >= c1


@pytest.mark.parametrize("qty", [0.1, 1, 5, 10, 20, 50, 100, 150, 200, 500])
def test_total_cost_positive_for_positive_qty(qty):
    cm = CostModel()
    c = cm.total_cost(price=1000.0, qty=float(qty), adv=1_000_000.0, spread_bps=5.0, side="BUY")
    assert c > 0.0


@pytest.mark.parametrize("qty", [1, 5, 10, 50, 100])
def test_stt_exactly_zero_on_buy_side(qty):
    cm = CostModel(k_impact=0.0, brokerage_per_trade=20.0, stt_rate=0.001)
    buy = cm.total_cost(price=1000.0, qty=float(qty), adv=10_000.0, spread_bps=0.0, side="BUY")
    assert abs(buy - 20.0) < 1e-12


@pytest.mark.parametrize("qty", [1, 5, 10, 50, 100])
def test_stt_exact_value_on_sell_side(qty):
    cm = CostModel(k_impact=0.0, brokerage_per_trade=20.0, stt_rate=0.001)
    sell = cm.total_cost(price=1000.0, qty=float(qty), adv=10_000.0, spread_bps=0.0, side="SELL")
    expected = 20.0 + 1000.0 * float(qty) * 0.001
    assert abs(sell - expected) < 1e-9


@pytest.mark.parametrize("qty", [0.0001, 0.001, 0.01, 0.05, 0.1])
def test_tiny_trade_still_includes_brokerage(qty):
    cm = CostModel(brokerage_per_trade=20.0)
    c = cm.total_cost(price=1000.0, qty=float(qty), adv=1_000_000.0, spread_bps=0.0, side="BUY")
    assert c >= 20.0
