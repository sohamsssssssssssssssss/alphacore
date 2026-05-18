from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import sqlalchemy as sa

from monitoring.health_check import ComponentStatus, HealthChecker, UptimeTracker


class _Alive:
    def is_alive(self):
        return True


class _Running:
    def is_running(self):
        return True


class _Broker:
    def ping(self):
        return True


def test_check_db_up_sqlite():
    hc = HealthChecker()
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    assert hc.check_db(engine) == ComponentStatus.UP


def test_check_db_down_unreachable_host():
    hc = HealthChecker()
    engine = sa.create_engine("postgresql://invalid.invalid:5432/alphacore", future=True)
    out = hc.check_db(engine)
    assert out in {ComponentStatus.DOWN, ComponentStatus.DEGRADED}


def test_check_gateway_down_closed_port():
    hc = HealthChecker()
    out = hc.check_gateway("127.0.0.1", 19999, timeout=0.1)
    assert out in {ComponentStatus.DOWN, ComponentStatus.DEGRADED}


def test_check_all_returns_all_keys():
    hc = HealthChecker()
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    out = hc.check_all(engine, "127.0.0.1", 19999, _Alive(), _Running(), _Broker())
    assert set(out.keys()) == {"db", "gateway", "feed", "engine", "broker"}


def test_check_all_down_triggers_post_slack_call():
    hc = HealthChecker(slack_webhook_url="https://example.com/webhook")
    engine = sa.create_engine("sqlite+pysqlite:///:memory:", future=True)
    with patch.object(hc, "_post_slack") as mock_post:
        _ = hc.check_all(engine, "127.0.0.1", 19999, object(), object(), object())
        mock_post.assert_called_once()


def test_uptime_pct_returns_100_with_no_data():
    ut = UptimeTracker()
    assert ut.uptime_pct("db") == 100.0


def test_uptime_records_and_pct_correct():
    ut = UptimeTracker()
    ut.record("db", ComponentStatus.UP)
    ut.record("db", ComponentStatus.UP)
    ut.record("db", ComponentStatus.UP)
    ut.record("db", ComponentStatus.DOWN)
    assert ut.uptime_pct("db") == 75.0


def test_is_meeting_sla_true_false():
    ut = UptimeTracker()
    ut.record("db", ComponentStatus.UP)
    assert ut.is_meeting_sla("db", 99.9) is True

    ut2 = UptimeTracker()
    ut2.record("db", ComponentStatus.UP)
    ut2.record("db", ComponentStatus.UP)
    ut2.record("db", ComponentStatus.UP)
    ut2.record("db", ComponentStatus.DOWN)
    assert ut2.is_meeting_sla("db", 99.9) is False


def test_uptime_pct_ignores_old_readings_outside_window():
    ut = UptimeTracker()
    old = datetime.now(UTC) - timedelta(days=40)
    ut._events.append((old, "db", ComponentStatus.DOWN))
    ut.record("db", ComponentStatus.UP)
    assert ut.uptime_pct("db", window_days=30) == 100.0
