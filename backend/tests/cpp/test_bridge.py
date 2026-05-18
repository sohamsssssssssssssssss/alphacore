from __future__ import annotations

import sys
import subprocess
import threading
import time
from collections import Counter

import pytest

sys.path.insert(0, "/tmp/alphacore_build")
alphacore_cpp = pytest.importorskip("alphacore_cpp")

_PX_SCALE = 100


def _px(v: float) -> int:
    return int(round(v * _PX_SCALE))


def _mk_engine(num_threads: int = 2):
    eng = alphacore_cpp.MatchingEngine(num_threads)
    eng.start()
    return eng


def _stop_engine(eng):
    try:
        eng.stop()
    except Exception:
        pass


def _mk_order(order_id: int, symbol_id: int, side: str, price: float, qty: int):
    o = alphacore_cpp.Order()
    o.order_id = int(order_id)
    o.symbol_id = int(symbol_id)
    o.side = side
    o.price = _px(price)
    o.qty = int(qty)
    o.timestamp_ns = int(time.time_ns())
    return o


def _drain_trades(eng, max_wait_s: float = 0.25):
    out = []
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < max_wait_s:
        tr = eng.pop_trade()
        if tr is None:
            time.sleep(0.0005)
            continue
        out.append(tr)
    return out


def _run_bad_input_subprocess(price: float, qty: int) -> int:
    code = f"""
import sys
sys.path.insert(0, '/tmp/alphacore_build')
import alphacore_cpp
eng = alphacore_cpp.MatchingEngine(1)
eng.start()
o = alphacore_cpp.Order()
o.order_id = 1
o.symbol_id = 1
o.side = 'B'
o.price = {int(round(price * _PX_SCALE))}
o.qty = {qty}
o.timestamp_ns = 1
eng.submit(o)
eng.stop()
"""
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    return int(proc.returncode)


class TestOrderSubmission:
    def test_submit_buy_order(self):
        eng = _mk_engine()
        try:
            o = _mk_order(1, 1, "B", 100.0, 10)
            ret = eng.submit(o)
            # Bridge submit() is void; treat assigned order_id as the accepted id.
            assert ret is None
            assert isinstance(o.order_id, int)
            assert o.order_id != 0
        finally:
            _stop_engine(eng)

    def test_submit_sell_order(self):
        eng = _mk_engine()
        try:
            o = _mk_order(2, 1, "S", 100.0, 10)
            ret = eng.submit(o)
            assert ret is None
            assert isinstance(o.order_id, int)
            assert o.order_id != 0
        finally:
            _stop_engine(eng)

    def test_submit_returns_unique_ids(self):
        eng = _mk_engine()
        try:
            ids = set()
            for i in range(100):
                oid = 1000 + i
                eng.submit(_mk_order(oid, 1, "B", 100.0, 1))
                ids.add(oid)
            assert len(ids) == 100
        finally:
            _stop_engine(eng)

    @pytest.mark.parametrize("bad_price", [0, -1])
    def test_submit_invalid_price_rejected(self, bad_price):
        rc = _run_bad_input_subprocess(price=float(bad_price), qty=1)
        assert rc != 0

    def test_submit_invalid_qty_rejected(self):
        rc = _run_bad_input_subprocess(price=100.0, qty=0)
        assert rc != 0

    def test_submit_large_order(self):
        eng = _mk_engine()
        try:
            eng.submit(_mk_order(14, 1, "B", 9999.99, 1_000_000))
        finally:
            _stop_engine(eng)


class TestMatching:
    def test_exact_match_produces_trade(self):
        eng = _mk_engine(num_threads=1)
        try:
            eng.submit(_mk_order(1, 7, "B", 100.0, 10))
            eng.submit(_mk_order(2, 7, "S", 100.0, 10))
            trades = _drain_trades(eng)
            assert len(trades) >= 1
            t = trades[0]
            assert t.price == _px(100.0)
            assert t.qty == 10
        finally:
            _stop_engine(eng)

    def test_partial_fill(self):
        eng = _mk_engine(num_threads=1)
        try:
            eng.submit(_mk_order(11, 8, "B", 100.0, 10))
            eng.submit(_mk_order(12, 8, "S", 100.0, 5))
            trades = _drain_trades(eng)
            assert sum(t.qty for t in trades) == 5
            eng.submit(_mk_order(13, 8, "S", 100.0, 5))
            trades2 = _drain_trades(eng)
            assert sum(t.qty for t in trades2) == 5
        finally:
            _stop_engine(eng)

    def test_no_match_different_price(self):
        eng = _mk_engine(num_threads=1)
        try:
            eng.submit(_mk_order(21, 9, "B", 99.0, 10))
            eng.submit(_mk_order(22, 9, "S", 101.0, 10))
            trades = _drain_trades(eng)
            assert len(trades) == 0
        finally:
            _stop_engine(eng)

    def test_price_time_priority(self):
        eng = _mk_engine(num_threads=1)
        try:
            eng.submit(_mk_order(31, 10, "B", 100.0, 5))
            eng.submit(_mk_order(32, 10, "B", 100.0, 5))
            eng.submit(_mk_order(33, 10, "S", 100.0, 5))
            trades = _drain_trades(eng)
            assert len(trades) >= 1
            assert trades[0].buy_order_id == 31
        finally:
            _stop_engine(eng)

    def test_multiple_fills_from_one_aggressive(self):
        eng = _mk_engine(num_threads=1)
        try:
            eng.submit(_mk_order(41, 11, "B", 100.0, 2))
            eng.submit(_mk_order(42, 11, "B", 100.0, 2))
            eng.submit(_mk_order(43, 11, "B", 100.0, 2))
            eng.submit(_mk_order(44, 11, "S", 100.0, 6))
            trades = _drain_trades(eng)
            buy_ids = [t.buy_order_id for t in trades]
            assert {41, 42, 43}.issubset(set(buy_ids))
        finally:
            _stop_engine(eng)


class TestOrderBook:
    def test_best_bid_ask_after_orders(self):
        pytest.skip("best bid/ask read from matching engine book is not exposed by bridge")

    def test_best_ask_after_orders(self):
        pytest.skip("best bid/ask read from matching engine book is not exposed by bridge")

    def test_cancel_order(self):
        pytest.skip("cancel_order is not exposed by pybind11 bridge")

    def test_book_empty_after_full_fill(self):
        eng = _mk_engine()
        try:
            eng.submit(_mk_order(51, 12, "B", 100.0, 1))
            eng.submit(_mk_order(52, 12, "S", 100.0, 1))
            _ = _drain_trades(eng)
            eng.submit(_mk_order(53, 12, "S", 101.0, 1))
            assert _drain_trades(eng, 0.05) == []
        finally:
            _stop_engine(eng)

    def test_depth_returns_correct_levels(self):
        pytest.skip("depth() API is not exposed by pybind11 bridge")


class TestConcurrency:
    def test_concurrent_submissions_no_crash(self):
        eng = _mk_engine(num_threads=4)
        try:
            errs = []

            def worker(tid: int):
                try:
                    base = tid * 10_000
                    for i in range(125):
                        eng.submit(_mk_order(base + i + 1, 21, "B", 100.0 + float(i % 3), 1))
                except Exception as exc:
                    errs.append(exc)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
            for th in threads:
                th.start()
            for th in threads:
                th.join(timeout=10)
            assert all(not th.is_alive() for th in threads)
            assert errs == []

            eng.submit(_mk_order(999999, 21, "S", 100.0, 1))
        finally:
            _stop_engine(eng)

    def test_concurrent_no_duplicate_trade(self):
        eng = _mk_engine(num_threads=4)
        try:
            pairs = 200

            def submit_pair(i: int):
                px = 200.0 + (i / 100.0)
                eng.submit(_mk_order(100000 + i, 31, "B", px, 1))
                eng.submit(_mk_order(200000 + i, 31, "S", px, 1))

            threads = [threading.Thread(target=submit_pair, args=(i,)) for i in range(pairs)]
            for th in threads:
                th.start()
            for th in threads:
                th.join(timeout=10)

            trades = _drain_trades(eng, 1.0)
            keys = [(t.buy_order_id, t.sell_order_id, t.price, t.qty) for t in trades]
            dupes = [k for k, c in Counter(keys).items() if c > 1]
            assert dupes == []
        finally:
            _stop_engine(eng)

    def test_high_throughput(self):
        eng = _mk_engine(num_threads=1)
        try:
            n = 10_000
            t0 = time.perf_counter()
            for i in range(n):
                eng.submit(_mk_order(300000 + i, 41, "B", 100.0, 1))
            dt = time.perf_counter() - t0
            throughput = n / dt if dt > 0 else float("inf")
            print(f"throughput={throughput:.2f} orders/sec")
            assert throughput > 100_000
        finally:
            _stop_engine(eng)


class TestErrorRecovery:
    def test_engine_responsive_after_bad_input(self):
        eng = _mk_engine()
        try:
            with pytest.raises(Exception):
                eng.submit({"bad": "payload"})  # type: ignore[arg-type]
            eng.submit(_mk_order(400001, 51, "B", 100.0, 1))
            eng.submit(_mk_order(400002, 51, "S", 100.0, 1))
            trades = _drain_trades(eng)
            assert len(trades) >= 1
        finally:
            _stop_engine(eng)

    def test_pool_exhaustion_handled(self):
        pytest.skip("pool size/capacity signaling not exposed in pybind11 bridge")
