from __future__ import annotations

import asyncio

from tests.load.load_test import LoadTestConfig, run_load_test


def test_load_test_small_run():
    result = asyncio.run(run_load_test(LoadTestConfig(n_orders=100, concurrency=10)))
    assert result.total_orders == 100
    assert isinstance(result.p99_ms, float)
    assert result.p99_ms > 0.0
    assert hasattr(result, "passed")


def test_latency_percentiles_ordered():
    result = asyncio.run(run_load_test(LoadTestConfig(n_orders=120, concurrency=12)))
    assert result.p50_ms <= result.p95_ms <= result.p99_ms


def test_chaos_does_not_crash():
    result = asyncio.run(run_load_test(LoadTestConfig(n_orders=50, concurrency=10, chaos_feed_interrupt_pct=1.0)))
    assert result.total_orders == 50
