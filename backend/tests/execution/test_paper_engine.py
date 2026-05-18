from __future__ import annotations

from execution.paper_engine import PaperTradingEngine


def test_market_order_fill():
    engine = PaperTradingEngine()
    engine.submit_order(symbol="SYMBOL", side="BUY", qty=10, order_type="MARKET")

    fills = engine.process_market_tick(symbol="SYMBOL", best_bid=99.0, best_ask=100.0)

    assert len(fills) == 1
    assert fills[0]["price"] == 100.0
    assert engine.positions["SYMBOL"] == 10


def test_limit_order_queue():
    engine = PaperTradingEngine()
    engine.submit_order(symbol="SYMBOL", side="BUY", qty=10, order_type="LIMIT", price=100.0)

    fills1 = engine.process_market_tick(symbol="SYMBOL", best_bid=101.0, best_ask=102.0)
    assert fills1 == []

    fills2 = engine.process_market_tick(symbol="SYMBOL", best_bid=99.0, best_ask=100.0)
    assert len(fills2) == 1
    assert fills2[0]["price"] == 100.0


def test_drawdown_calculation():
    engine = PaperTradingEngine(starting_capital=100000.0)

    engine.submit_order(symbol="SYMBOL", side="BUY", qty=10, order_type="MARKET")
    _ = engine.process_market_tick(symbol="SYMBOL", best_bid=100.0, best_ask=100.0)

    # Mark a strong down move to generate >5% drawdown via unrealized loss.
    _ = engine.process_market_tick(symbol="SYMBOL", best_bid=-410.0, best_ask=-410.0)

    metrics = engine.get_realtime_metrics()
    assert metrics["max_drawdown"] >= 0.05


def test_partial_position_tracking():
    engine = PaperTradingEngine()

    engine.submit_order(symbol="SYMBOL", side="BUY", qty=10, order_type="MARKET")
    _ = engine.process_market_tick(symbol="SYMBOL", best_bid=100.0, best_ask=100.0)

    engine.submit_order(symbol="SYMBOL", side="SELL", qty=5, order_type="MARKET")
    _ = engine.process_market_tick(symbol="SYMBOL", best_bid=100.0, best_ask=101.0)

    assert engine.positions["SYMBOL"] == 5
