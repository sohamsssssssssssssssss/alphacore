from __future__ import annotations

import pytest

from execution.kite_broker import KiteBroker
from kiteconnect.exceptions import NetworkException


def _make_broker(monkeypatch):
    class _FakeKite:
        TRANSACTION_TYPE_BUY = "BUY"
        TRANSACTION_TYPE_SELL = "SELL"
        VARIETY_REGULAR = "regular"
        EXCHANGE_NSE = "NSE"

        def __init__(self, api_key):
            self.api_key = api_key
            self.access_token = None
            self.place_order_kwargs = None

        def set_access_token(self, token):
            self.access_token = token

        def place_order(self, **kwargs):
            self.place_order_kwargs = kwargs
            return "order_123"

        def positions(self):
            return {"net": []}

        def cancel_order(self, variety, order_id):
            return True

        def order_history(self, order_id):
            return [{"status": "COMPLETE"}]

    monkeypatch.setattr("execution.kite_broker.KiteConnect", _FakeKite)
    return KiteBroker(api_key="k", access_token="t")


def test_place_market_order(monkeypatch):
    broker = _make_broker(monkeypatch)

    order_id = broker.place_order("RELIANCE", "BUY", 1, "MARKET", "MIS")

    assert isinstance(order_id, str)
    assert broker.kite.place_order_kwargs["order_type"] == "MARKET"
    assert broker.kite.place_order_kwargs["variety"] == "regular"


def test_place_sl_order(monkeypatch):
    broker = _make_broker(monkeypatch)

    _ = broker.place_order("RELIANCE", "BUY", 1, "SL", "MIS", trigger_price=2400.0)

    assert broker.kite.place_order_kwargs["trigger_price"] == 2400.0


def test_api_exception_handling(monkeypatch):
    broker = _make_broker(monkeypatch)

    def _raise(**kwargs):
        raise NetworkException("network down", code=500)

    broker.kite.place_order = _raise

    with pytest.raises(NetworkException):
        broker.place_order("RELIANCE", "BUY", 1, "MARKET", "MIS")


def test_get_positions_standardised(monkeypatch):
    broker = _make_broker(monkeypatch)
    broker.kite.positions = lambda: {
        "net": [
            {
                "tradingsymbol": "RELIANCE",
                "quantity": 3,
                "average_price": 2450.5,
                "pnl": 120.0,
                "product": "MIS",
            }
        ]
    }

    out = broker.get_positions()

    assert isinstance(out, list)
    assert out[0]["symbol"] == "RELIANCE"
    assert out[0]["qty"] == 3
