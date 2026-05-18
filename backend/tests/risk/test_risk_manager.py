from __future__ import annotations

import pytest

from risk.risk_manager import RiskGate, RiskViolationException


def test_max_position_breach():
    gate = RiskGate(max_position_inr=50000)
    with pytest.raises(RiskViolationException):
        gate.evaluate_order("RELIANCE", "BUY", 10, 5100.0, {}, 0, 0)


def test_daily_loss_breach():
    gate = RiskGate(max_daily_loss=5000)
    with pytest.raises(RiskViolationException):
        gate.evaluate_order("TCS", "BUY", 1, 100.0, {}, -5001.0, 0)


def test_drawdown_breach():
    gate = RiskGate(max_drawdown_pct=0.05, starting_capital=100000)
    with pytest.raises(RiskViolationException):
        gate.evaluate_order("INFY", "BUY", 1, 100.0, {}, 4000, 10000)


def test_safe_order_passes():
    gate = RiskGate()
    result = gate.evaluate_order("SBIN", "BUY", 1, 100.0, {}, 0, 0)
    assert result is True


def test_price_dump_halts_symbol():
    gate = RiskGate(max_price_drop_pct=0.03, price_drop_window_seconds=120.0)
    # Record a starting price
    gate.record_price("RELIANCE", 100.0)
    # Simulate a 4% drop (exceeds 3% threshold)
    dumped = gate.check_price_dump("RELIANCE", 96.0)
    assert dumped is True
    assert "RELIANCE" in gate._halted_symbols


def test_price_drop_below_threshold_not_halted():
    gate = RiskGate(max_price_drop_pct=0.03, price_drop_window_seconds=120.0)
    gate.record_price("TCS", 100.0)
    # Only 1% drop, below threshold
    dumped = gate.check_price_dump("TCS", 99.0)
    assert dumped is False
    assert "TCS" not in gate._halted_symbols


def test_halted_symbol_blocks_order():
    gate = RiskGate(max_price_drop_pct=0.03, price_drop_window_seconds=120.0)
    gate.record_price("INFY", 100.0)
    gate.check_price_dump("INFY", 96.0)  # triggers halt
    import pytest
    with pytest.raises(RiskViolationException) as exc_info:
        gate.evaluate_order(
            symbol="INFY",
            side="B",
            qty=10,
            price=96.0,
            current_positions={},
            current_pnl=0.0,
            peak_pnl=0.0,
        )
    assert exc_info.value.rule == "price_dump_halt"


def test_price_pump_halts_symbol():
    gate = RiskGate(max_price_rise_pct=0.03)
    gate.record_price("WIPRO", 100.0)
    pumped = gate.check_price_pump("WIPRO", 104.0)
    assert pumped is True
    assert "WIPRO" in gate._halted_symbols


def test_price_rise_below_threshold_not_halted():
    gate = RiskGate(max_price_rise_pct=0.03)
    gate.record_price("WIPRO", 100.0)
    pumped = gate.check_price_pump("WIPRO", 101.0)
    assert pumped is False
    assert "WIPRO" not in gate._halted_symbols
