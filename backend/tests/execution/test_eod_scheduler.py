from __future__ import annotations

from unittest.mock import Mock

from execution.eod_scheduler import EODScheduler


def test_flatten_long_position():
    broker = Mock()
    broker.get_positions.return_value = [{"symbol": "INFY", "qty": 100}]
    broker.get_pending_orders.return_value = []

    scheduler = EODScheduler(broker, dry_run=False)
    scheduler.flatten_all_positions()

    broker.place_order.assert_called_once_with("INFY", "SELL", 100, "MARKET", "MIS")


def test_flatten_short_position():
    broker = Mock()
    broker.get_positions.return_value = [{"symbol": "TCS", "qty": -50}]
    broker.get_pending_orders.return_value = []

    scheduler = EODScheduler(broker, dry_run=False)
    scheduler.flatten_all_positions()

    broker.place_order.assert_called_once_with("TCS", "BUY", 50, "MARKET", "MIS")


def test_dry_run_no_orders():
    broker = Mock()
    broker.get_positions.return_value = [{"symbol": "INFY", "qty": 100}]
    broker.get_pending_orders.return_value = [{"order_id": "abc"}]

    scheduler = EODScheduler(broker, dry_run=True)
    scheduler.flatten_all_positions()

    broker.place_order.assert_not_called()
    broker.cancel_order.assert_not_called()


def test_zero_position_skipped():
    broker = Mock()
    broker.get_positions.return_value = [{"symbol": "SBIN", "qty": 0}]
    broker.get_pending_orders.return_value = []

    scheduler = EODScheduler(broker, dry_run=False)
    scheduler.flatten_all_positions()

    broker.place_order.assert_not_called()
