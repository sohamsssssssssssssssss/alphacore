from __future__ import annotations

from strategy.alpha_strategy import AlphaStrategy


def test_signal_reaction_high_confidence():
    strategy = AlphaStrategy(confidence_threshold=0.8, base_qty=10)
    strategy.on_orderbook("RELIANCE", [[2400, 100]], [[2401, 100]])
    strategy.on_signal("RELIANCE", "lgbm", 0.9, 0.85)

    orders = strategy.get_pending_orders()
    assert len(orders) == 1
    assert orders[0]["side"] == "BUY"


def test_signal_reaction_low_confidence():
    strategy = AlphaStrategy(confidence_threshold=0.8, base_qty=10)
    strategy.on_signal("RELIANCE", "lgbm", 0.9, 0.7)
    assert strategy.get_pending_orders() == []


def test_regime_change_cuts_qty():
    strategy = AlphaStrategy(base_qty=10)
    strategy.on_regime_change(0, 3)
    assert strategy.base_qty == 5


def test_regime_restore():
    strategy = AlphaStrategy(base_qty=10)
    strategy.on_regime_change(0, 3)
    strategy.on_regime_change(3, 0)
    assert strategy.base_qty == 10
