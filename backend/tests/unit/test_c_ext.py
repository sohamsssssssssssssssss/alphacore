from __future__ import annotations

import pytest

from c_ext import FastDetector, FastOrderBook, c_ext_available


pytestmark = pytest.mark.skipif(not c_ext_available, reason="C extension not built")


def test_fast_orderbook_insert_and_best_levels():
    ob = FastOrderBook()
    ob.clear()
    ob.insert_bid(100, 10)
    ob.insert_bid(101, 20)
    ob.insert_ask(102, 15)
    ob.insert_ask(103, 5)
    assert ob.best_bid()[0] == 101
    assert ob.best_ask()[0] == 102


def test_fast_orderbook_mid_and_spread_positive():
    ob = FastOrderBook()
    ob.clear()
    ob.insert_bid(100, 10)
    ob.insert_ask(101, 10)
    assert ob.mid_price() == pytest.approx(100.5)
    assert ob.spread_bps() > 0


def test_fast_orderbook_clear_resets():
    ob = FastOrderBook()
    ob.insert_bid(100, 10)
    ob.insert_ask(101, 10)
    ob.clear()
    assert ob.best_bid() == (0.0, 0.0)
    assert ob.best_ask() == (0.0, 0.0)


def test_fast_detector_iceberg_detected():
    fd = FastDetector()
    levels = [(100, 10000), (99.9, 100), (99.8, 100)]
    out = fd.iceberg_scan(levels, threshold=0.7)
    assert out["detected"] == 1
    assert out["level_idx"] == 0
    assert out["confidence"] > 0.7


def test_fast_detector_iceberg_not_detected_balanced():
    fd = FastDetector()
    levels = [(100, 100), (99.9, 100), (99.8, 100)]
    out = fd.iceberg_scan(levels, threshold=0.7)
    assert out["detected"] == 0


def test_fast_detector_spoof_positive_when_large_far_disappears():
    fd = FastDetector()
    prev = [(102, 20000), (101, 5000), (100, 2000)]
    cur = [(102, 0), (101, 5000), (100, 2000)]
    score = fd.spoof_scan(cur, prev, mid_price=100.0, dist_bps=100, qty_thresh=10000)
    assert score > 0


def test_fast_detector_spoof_zero_when_no_suspicious_cancel():
    fd = FastDetector()
    prev = [(100, 1000), (99.9, 900)]
    cur = [(100, 1000), (99.9, 900)]
    score = fd.spoof_scan(cur, prev, mid_price=100.0, dist_bps=200, qty_thresh=10000)
    assert score == 0.0
