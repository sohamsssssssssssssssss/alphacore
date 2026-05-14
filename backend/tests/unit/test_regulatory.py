from __future__ import annotations

from datetime import datetime, timedelta

from engines.circuit_breaker import CircuitBreaker
from engines.kill_switch import KillSwitch
from engines.otr_monitor import OTRMonitor
from engines.risk_limits import (
    MAX_POSITION_SIZE,
    MAX_SIGNALS_PER_SYMBOL_PER_HOUR,
    RiskLimits,
)


def test_circuit_breaker_triggers_on_above_five_percent_move():
    cb = CircuitBreaker()
    assert cb.check("RELIANCE", current_price=106.0, prev_price=100.0) is True


def test_circuit_breaker_does_not_trigger_below_five_percent_move():
    cb = CircuitBreaker()
    assert cb.check("RELIANCE", current_price=104.99, prev_price=100.0) is False


def test_circuit_breaker_exact_five_percent_does_not_trigger():
    cb = CircuitBreaker()
    assert cb.check("RELIANCE", current_price=105.0, prev_price=100.0) is False


def test_circuit_breaker_rechecks_halted_symbol_as_halted():
    cb = CircuitBreaker()
    cb.check("RELIANCE", current_price=106.0, prev_price=100.0)
    assert cb.check("RELIANCE", current_price=101.0, prev_price=100.0) is True


def test_circuit_breaker_reset_clears_halt():
    cb = CircuitBreaker()
    cb.check("RELIANCE", current_price=106.0, prev_price=100.0)
    cb.reset("RELIANCE")
    assert cb.status() == {}


def test_circuit_breaker_status_contains_reason_and_halt_time():
    cb = CircuitBreaker()
    cb.check("RELIANCE", current_price=106.0, prev_price=100.0)
    status = cb.status()["RELIANCE"]
    assert "reason" in status
    assert "halted_at" in status
    assert status["price_at_halt"] == 106.0


def test_kill_switch_initial_state_inactive():
    ks = KillSwitch()
    assert ks.is_active is False


def test_kill_switch_activate_sets_status():
    ks = KillSwitch()
    ks.activate("ops trigger")
    status = ks.status()
    assert ks.is_active is True
    assert status["reason"] == "ops trigger"
    assert status["activated_at"] is not None


def test_kill_switch_deactivate_resets_state():
    ks = KillSwitch()
    ks.activate("ops trigger")
    ks.deactivate()
    status = ks.status()
    assert ks.is_active is False
    assert status["reason"] is None
    assert status["activated_at"] is None


def test_otr_record_order_and_trade_updates_ratio():
    monitor = OTRMonitor()
    monitor.record_order("RELIANCE")
    monitor.record_order("RELIANCE")
    monitor.record_trade("RELIANCE")
    assert monitor.get_otr("RELIANCE") == 2.0


def test_otr_without_trades_returns_order_count_as_float():
    monitor = OTRMonitor()
    monitor.record_order("RELIANCE")
    monitor.record_order("RELIANCE")
    assert monitor.get_otr("RELIANCE") == 2.0


def test_otr_breach_detection_above_threshold():
    monitor = OTRMonitor(threshold=3.0)
    for _ in range(4):
        monitor.record_order("RELIANCE")
    monitor.record_trade("RELIANCE")
    assert monitor.is_breached("RELIANCE") is True


def test_otr_not_breached_at_threshold():
    monitor = OTRMonitor(threshold=4.0)
    for _ in range(4):
        monitor.record_order("RELIANCE")
    monitor.record_trade("RELIANCE")
    assert monitor.is_breached("RELIANCE") is False


def test_otr_summary_contains_symbol_metrics():
    monitor = OTRMonitor()
    monitor.record_order("RELIANCE")
    summary = monitor.summary()
    assert "RELIANCE" in summary
    assert summary["RELIANCE"]["orders"] == 1


def test_risk_limits_blocks_excess_notional():
    limits = RiskLimits()
    allowed, reason = limits.check_signal("RELIANCE", entry_price=(MAX_POSITION_SIZE / 100.0) + 1.0)
    assert allowed is False
    assert "exceeds max" in reason


def test_risk_limits_blocks_rate_limit_per_hour():
    limits = RiskLimits()
    now = datetime.utcnow()
    limits._signal_counts["RELIANCE"] = [
        now - timedelta(minutes=5) for _ in range(MAX_SIGNALS_PER_SYMBOL_PER_HOUR)
    ]
    allowed, reason = limits.check_signal("RELIANCE", entry_price=900.0)
    assert allowed is False
    assert "Signal rate limit" in reason


def test_risk_limits_allows_valid_signal_and_records_count():
    limits = RiskLimits()
    allowed, reason = limits.check_signal("RELIANCE", entry_price=900.0)
    assert allowed is True
    assert reason == "ok"
    assert len(limits._signal_counts["RELIANCE"]) == 1


def test_risk_limits_purges_old_entries_from_count_window():
    limits = RiskLimits()
    old_time = datetime.utcnow() - timedelta(hours=2)
    limits._signal_counts["RELIANCE"] = [old_time]
    allowed, _ = limits.check_signal("RELIANCE", entry_price=900.0)
    assert allowed is True
    assert len(limits._signal_counts["RELIANCE"]) == 1
