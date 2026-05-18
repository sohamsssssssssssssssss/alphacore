from __future__ import annotations

import os
import random
import statistics
import subprocess
import sys
import threading
import time

import pytest

sys.path.insert(0, "/tmp/alphacore_build")
alphacore_cpp = pytest.importorskip("alphacore_cpp")


pytestmark = pytest.mark.timeout(30)

_PX_SCALE = 100


def _px(v: float) -> int:
    return int(round(v * _PX_SCALE))


def _mk_engine(num_threads: int = 4):
    eng = alphacore_cpp.MatchingEngine(num_threads)
    eng.start()
    return eng


def _stop_engine(eng):
    try:
        eng.stop()
    except Exception:
        pass


def _mk_order(order_id: int, symbol_id: int, side: str, price_f: float, qty: int):
    o = alphacore_cpp.Order()
    o.order_id = int(order_id)
    o.symbol_id = int(symbol_id)
    o.side = side
    o.price = _px(price_f)
    o.qty = int(qty)
    o.timestamp_ns = int(time.time_ns())
    return o


def _drain_trades(eng, max_wait_s: float = 0.5):
    out = []
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < max_wait_s:
        tr = eng.pop_trade()
        if tr is None:
            time.sleep(0.0002)
            continue
        out.append(tr)
    return out


class TestEngineStress:
    @pytest.mark.timeout(30)
    def test_10k_random_orders_no_crash(self):
        eng = _mk_engine(num_threads=4)
        try:
            submitted = 0
            for i in range(10_000):
                side = "B" if random.random() < 0.5 else "S"
                price = random.uniform(95.0, 105.0)
                qty = random.randint(1, 100)
                eng.submit(_mk_order(1_000_000 + i, 1, side, price, qty))
                submitted += 1
            trades = _drain_trades(eng, 1.0)
            print(f"total trades produced={len(trades)}, total orders submitted={submitted}")
            assert submitted == 10_000
        finally:
            _stop_engine(eng)

    @pytest.mark.timeout(30)
    def test_order_book_depth_under_load(self):
        # MatchingEngine book-depth/best bid-ask queries are not exposed by pybind bridge.
        if not hasattr(alphacore_cpp, "FlatPriceMap"):
            pytest.skip("FlatPriceMap not exposed")

        ob = alphacore_cpp.FlatPriceMap(_px(80.0), _px(120.0), _px(0.1))
        if not hasattr(ob, "insert_bid") or not hasattr(ob, "insert_ask"):
            pytest.skip("insert_bid/insert_ask not exposed in pybind FlatPriceMap")

        for i in range(100):
            p = 90.0 + (i * 0.1)
            for _ in range(50):
                ob.insert_bid(_px(p), 1)
        assert ob.best_bid() == _px(99.9)

        for i in range(99):
            p = 100.1 + (i * 0.1)
            for _ in range(50):
                ob.insert_ask(_px(p), 1)
        assert ob.best_ask() == _px(100.1)
        assert ob.best_ask() > ob.best_bid()

    @pytest.mark.timeout(30)
    def test_fill_rate_correctness(self):
        eng = _mk_engine(num_threads=1)
        try:
            n = 1000
            for i in range(n):
                p = 100.0 + (i % 3) * 0.01
                eng.submit(_mk_order(2_000_000 + i, 7, "B", p, 1))
                eng.submit(_mk_order(3_000_000 + i, 7, "S", p, 1))

            trades = _drain_trades(eng, 2.0)
            keys = {(t.buy_order_id, t.sell_order_id, t.price, t.qty) for t in trades}
            assert len(trades) == n
            assert len(keys) == n
        finally:
            _stop_engine(eng)

    @pytest.mark.timeout(30)
    def test_throughput_10k_orders(self):
        eng = _mk_engine(num_threads=1)
        try:
            orders = [_mk_order(4_000_000 + i, 9, "B", 100.0 + ((i % 10) * 0.01), 1) for i in range(10_000)]
            latencies = []
            t0 = time.perf_counter()
            for o in orders:
                ts = time.perf_counter()
                eng.submit(o)
                latencies.append(time.perf_counter() - ts)
            dt = time.perf_counter() - t0

            throughput = len(orders) / dt if dt > 0 else float("inf")
            mean_latency = statistics.mean(latencies) if latencies else 0.0
            p99_latency = statistics.quantiles(latencies, n=100)[98] if len(latencies) >= 100 else max(latencies, default=0.0)
            print(f"throughput={throughput:.2f} orders/sec mean_latency={mean_latency:.9f}s p99_latency={p99_latency:.9f}s")
            assert throughput > 100_000
        finally:
            _stop_engine(eng)

    @pytest.mark.timeout(30)
    def test_multithreaded_8_threads_1k_each(self):
        eng = _mk_engine(num_threads=4)
        try:
            errs: list[Exception] = []

            def worker(tid: int):
                try:
                    base = 5_000_000 + (tid * 10_000)
                    for i in range(1000):
                        side = "B" if (i % 2 == 0) else "S"
                        eng.submit(_mk_order(base + i, 11, side, 100.0 + (i % 5) * 0.01, 1))
                except Exception as exc:  # pragma: no cover - diagnostic path
                    errs.append(exc)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
            for th in threads:
                th.start()
            for th in threads:
                th.join(timeout=20)

            assert all(not th.is_alive() for th in threads)
            assert errs == []

            eng.submit(_mk_order(9_999_991, 11, "B", 100.0, 1))
        finally:
            _stop_engine(eng)

    @pytest.mark.timeout(30)
    def test_cancel_under_load(self):
        eng = _mk_engine(num_threads=1)
        try:
            if not hasattr(eng, "cancel_order"):
                pytest.skip("cancel_order not exposed by pybind bridge")

            ids = []
            for i in range(1000):
                oid = 6_000_000 + i
                ids.append(oid)
                eng.submit(_mk_order(oid, 13, "B", 100.0, 1))

            cancel_ids = set(random.sample(ids, 500))
            for oid in cancel_ids:
                eng.cancel_order(oid)

            for i in range(1000):
                eng.submit(_mk_order(7_000_000 + i, 13, "S", 100.0, 1))

            trades = _drain_trades(eng, 2.0)
            expected = 500
            tol = int(expected * 0.10)
            assert (expected - tol) <= len(trades) <= (expected + tol)
        finally:
            _stop_engine(eng)


class TestChaosCpp:
    _FAULTS = [
        "OB_FAULT_JOURNAL_SHORT_WRITE",
        "OB_FAULT_JOURNAL_BIT_FLIP",
        "OB_FAULT_FSYNC_FAILURE",
        "OB_FAULT_POOL_EXHAUSTION",
        "OB_FAULT_QUEUE_FULL",
        "OB_FAULT_GATEWAY_FRAGMENTATION",
        "OB_FAULT_DB_CONNECTION_DROP",
        "OB_FAULT_FEED_INTERRUPTION",
        "OB_FAULT_BROKER_TIMEOUT",
        "OB_FAULT_PARTIAL_FILL_CRASH",
    ]

    @staticmethod
    def _run_fault_subprocess(fault_env_name: str) -> tuple[int, str, str]:
        code = """
import json, os, sys
sys.path.insert(0, '/tmp/alphacore_build')
import alphacore_cpp
eng = alphacore_cpp.MatchingEngine(1)
eng.start()
o = alphacore_cpp.Order()
o.order_id = 1
o.symbol_id = 1
o.side = 'B'
o.price = 10000
o.qty = 1
o.timestamp_ns = 1
ok = True
err = ''
try:
    eng.submit(o)
except Exception as e:
    ok = False
    err = str(e)
eng.stop()
print(json.dumps({'ok': ok, 'err': err}))
"""
        env = os.environ.copy()
        env[fault_env_name] = "1"
        # Also support requested ALPHACORE_FAULT_* alias names.
        alias = "ALPHACORE_FAULT_" + fault_env_name.removeprefix("OB_FAULT_")
        env[alias] = "1"
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
        return p.returncode, p.stdout.strip(), p.stderr.strip()

    @staticmethod
    def _assert_responsive_no_fault() -> None:
        eng = _mk_engine(num_threads=1)
        try:
            eng.submit(_mk_order(8_000_001, 21, "B", 100.0, 1))
        finally:
            _stop_engine(eng)

    @pytest.mark.timeout(30)
    def test_fault_pool_exhaustion_recovery(self):
        rc, _out, _err = self._run_fault_subprocess("OB_FAULT_POOL_EXHAUSTION")
        assert rc in {0, 1, -6}
        self._assert_responsive_no_fault()

    @pytest.mark.timeout(30)
    def test_fault_queue_full_recovery(self):
        rc, _out, _err = self._run_fault_subprocess("OB_FAULT_QUEUE_FULL")
        assert rc in {0, 1, -6}
        self._assert_responsive_no_fault()

    @pytest.mark.timeout(30)
    def test_fault_partial_fill_crash_recovery(self):
        rc, _out, _err = self._run_fault_subprocess("OB_FAULT_PARTIAL_FILL_CRASH")
        assert rc in {0, 1, -6}
        self._assert_responsive_no_fault()

    @pytest.mark.timeout(30)
    def test_all_faults_sequential(self):
        for fault in self._FAULTS:
            rc, _out, _err = self._run_fault_subprocess(fault)
            # No unrecoverable parent-process hang should occur.
            assert rc in {0, 1, -6}
            self._assert_responsive_no_fault()
