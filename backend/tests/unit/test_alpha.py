from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from engines.alpha_engine import AlphaEngine
from engines.signals.combiner import SignalCombiner
from engines.signals.mean_reversion import MeanReversionSignal
from engines.signals.momentum import MomentumSignal
from engines.signals.order_flow import OrderFlowSignal


def test_momentum_single_update_no_signal():
    m = MomentumSignal()
    m.update("RELIANCE", 100.0, datetime.now(timezone.utc))
    assert m.compute("RELIANCE") is None


def test_momentum_sufficient_history():
    m = MomentumSignal()
    now = datetime.now(timezone.utc)
    m.update("RELIANCE", 100.0, now - timedelta(minutes=16))
    m.update("RELIANCE", 101.0, now - timedelta(minutes=6))
    m.update("RELIANCE", 102.0, now - timedelta(minutes=2))
    m.update("RELIANCE", 103.0, now)
    assert m.compute("RELIANCE") is not None


def test_momentum_direction_long():
    m = MomentumSignal()
    now = datetime.now(timezone.utc)
    for i, p in enumerate([100, 101, 102, 103]):
        m.update("RELIANCE", p, now - timedelta(minutes=16 - i * 5))
    assert m.compute("RELIANCE")["direction"] == "LONG"


def test_momentum_direction_short():
    m = MomentumSignal()
    now = datetime.now(timezone.utc)
    m.update("RELIANCE", 103, now - timedelta(minutes=16))
    m.update("RELIANCE", 102, now - timedelta(minutes=6))
    m.update("RELIANCE", 101, now - timedelta(minutes=2))
    m.update("RELIANCE", 100, now)
    assert m.compute("RELIANCE")["direction"] == "SHORT"


def test_meanrev_insufficient_history():
    mr = MeanReversionSignal()
    mr.update("TCS", 100.0, datetime.now(timezone.utc))
    assert mr.compute("TCS") is None


def test_meanrev_z_score_positive():
    mr = MeanReversionSignal()
    now = datetime.now(timezone.utc)
    for i in range(20):
        mr.update("TCS", 100 + (i * 0.1), now + timedelta(seconds=i))
    assert mr.compute("TCS")["z_score"] >= 0


def test_meanrev_z_score_negative():
    mr = MeanReversionSignal()
    now = datetime.now(timezone.utc)
    vals = [100 + i * 0.1 for i in range(19)] + [95]
    for i, v in enumerate(vals):
        mr.update("TCS", v, now + timedelta(seconds=i))
    assert mr.compute("TCS")["z_score"] < 0


def test_meanrev_direction_long():
    mr = MeanReversionSignal()
    now = datetime.now(timezone.utc)
    vals = [100 + i * 0.1 for i in range(19)] + [90]
    for i, v in enumerate(vals):
        mr.update("TCS", v, now + timedelta(seconds=i))
    assert mr.compute("TCS")["direction"] == "LONG"


def test_orderflow_ofi_bid_heavy():
    of = OrderFlowSignal()
    of.update("INFY", [(100, 100)] * 5, [(101, 10)] * 5)
    assert of.compute("INFY")["direction"] == "LONG"


def test_orderflow_ofi_ask_heavy():
    of = OrderFlowSignal()
    of.update("INFY", [(100, 10)] * 5, [(101, 100)] * 5)
    assert of.compute("INFY")["direction"] == "SHORT"


def test_orderflow_neutral():
    of = OrderFlowSignal()
    of.update("INFY", [(100, 10)] * 5, [(101, 10)] * 5)
    assert of.compute("INFY")["direction"] == "FLAT"


def test_combiner_equal_weights_default():
    c = SignalCombiner()
    w = c.get_weights("RELIANCE")
    assert w["momentum"] == pytest.approx(1 / 3)


def test_combiner_majority_vote_long():
    c = SignalCombiner()
    out = c.combine("RELIANCE", {"signal": 5, "direction": "LONG", "strength": 1}, {"signal": 1, "direction": "LONG", "strength": 0.5}, {"signal": -1, "direction": "SHORT", "strength": 0.2})
    assert out["combined_direction"] == "LONG"


def test_combiner_majority_vote_short():
    c = SignalCombiner()
    out = c.combine("RELIANCE", {"signal": -5, "direction": "SHORT", "strength": 1}, {"signal": -1, "direction": "SHORT", "strength": 0.5}, {"signal": 1, "direction": "LONG", "strength": 0.2})
    assert out["combined_direction"] == "SHORT"


def test_combiner_confidence_all_agree():
    c = SignalCombiner()
    out = c.combine("RELIANCE", {"signal": 2, "direction": "LONG", "strength": 1}, {"signal": 3, "direction": "LONG", "strength": 1}, {"signal": 4, "direction": "LONG", "strength": 1})
    assert out["confidence"] == 1.0


def test_combiner_confidence_mixed():
    c = SignalCombiner()
    out = c.combine("RELIANCE", {"signal": 2, "direction": "LONG", "strength": 1}, {"signal": -3, "direction": "SHORT", "strength": 1}, {"signal": 0, "direction": "FLAT", "strength": 0})
    assert out["confidence"] == 0.0


def test_alpha_engine_update_and_compute():
    e = AlphaEngine()
    now = datetime.now(timezone.utc)
    for i in range(25):
        p = 100 + i * 0.1
        bids = [(p - 0.1, 100 + i)] * 5
        asks = [(p + 0.1, 95 + i)] * 5
        e.update("RELIANCE", p, now + timedelta(seconds=i * 40), bids, asks)
    res = e.compute("RELIANCE")
    assert res["symbol"] == "RELIANCE"
    assert "combined" in res


def test_alpha_engine_get_all_five_symbols():
    e = AlphaEngine()
    rows = e.get_all()
    assert len(rows) == 5
