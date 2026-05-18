from __future__ import annotations

from pathlib import Path

from paper_runner import PaperSession
from risk.risk_manager import RiskViolationException


def test_session_instantiates(tmp_path):
    s = PaperSession(starting_capital=100000.0, audit_db=str(tmp_path / "audit.db"))
    assert s is not None


def test_on_tick_valid_bar(tmp_path):
    s = PaperSession(starting_capital=100000.0, audit_db=str(tmp_path / "audit.db"))
    bar = {
        "symbol": "RELIANCE",
        "open": 2500.0,
        "high": 2502.0,
        "low": 2498.0,
        "close": 2501.0,
        "volume": 1000.0,
        "timestamp": "2026-01-01T10:00:00+00:00",
    }
    s._on_tick(bar)


def test_on_tick_risk_violation_logged(tmp_path):
    s = PaperSession(starting_capital=100000.0, audit_db=str(tmp_path / "audit.db"))

    def _raise(*args, **kwargs):
        raise RiskViolationException("test_rule", 2.0, 1.0)

    s.risk_gate.evaluate_order = _raise

    bar = {
        "symbol": "RELIANCE",
        "open": 2500.0,
        "high": 2502.0,
        "low": 2498.0,
        "close": 2501.0,
        "volume": 1000.0,
        "timestamp": "2026-01-01T10:00:00+00:00",
    }
    s._on_tick(bar)

    today = "2026-01-01"
    # Use current session date dynamically from latest event timestamp in IST day.
    rows = s.audit.replay_session(__import__("datetime").datetime.now(__import__("datetime").timezone.utc).astimezone(__import__("datetime").timezone(__import__("datetime").timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d"))
    assert any(r.get("event_type") == "RISK_VIOLATION" for r in rows)


def test_on_tick_bad_bar_does_not_crash(tmp_path):
    s = PaperSession(starting_capital=100000.0, audit_db=str(tmp_path / "audit.db"))
    s._on_tick({})


def test_print_summary_runs(tmp_path):
    s = PaperSession(starting_capital=100000.0, audit_db=str(tmp_path / "audit.db"))
    s.print_summary()
