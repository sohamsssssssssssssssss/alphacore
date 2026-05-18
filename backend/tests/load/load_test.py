from __future__ import annotations

import asyncio
import random
import statistics
import sys
import time
from dataclasses import dataclass

try:
    from backend.execution.paper_engine import PaperTradingEngine
    from backend.risk.risk_manager import RiskGate, RiskViolationException
except Exception:
    from execution.paper_engine import PaperTradingEngine
    from risk.risk_manager import RiskGate, RiskViolationException


@dataclass
class LoadTestConfig:
    n_orders: int = 10000
    concurrency: int = 100
    target_p99_ms: float = 1.0
    chaos_feed_interrupt_pct: float = 0.05


@dataclass
class LoadTestResult:
    p50_ms: float
    p95_ms: float
    p99_ms: float
    total_orders: int
    failed_orders: int
    duration_s: float
    passed: bool


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    idx = int(round((p / 100.0) * (len(sorted_vals) - 1)))
    idx = max(0, min(idx, len(sorted_vals) - 1))
    return float(sorted_vals[idx])


async def submit_order(engine, order_dict, results_list) -> None:
    t0 = time.perf_counter()
    try:
        engine.submit_order(
            symbol=order_dict["symbol"],
            side=order_dict["side"],
            qty=order_dict["qty"],
            order_type=order_dict["order_type"],
            price=order_dict.get("price"),
        )
        t1 = time.perf_counter()
        results_list["latencies_ms"].append((t1 - t0) * 1000.0)
    except RiskViolationException:
        results_list["failed_orders"] += 1
    except Exception:
        results_list["failed_orders"] += 1


async def run_load_test(config: LoadTestConfig) -> LoadTestResult:
    engine = PaperTradingEngine(starting_capital=10_000_000.0)
    gate = RiskGate(starting_capital=10_000_000.0)

    symbols = ["RELIANCE", "TCS", "INFY", "HDFC", "WIPRO"]
    latencies_state = {"latencies_ms": [], "failed_orders": 0}

    orders: list[dict] = []
    for _ in range(int(config.n_orders)):
        order = {
            "symbol": random.choice(symbols),
            "side": random.choice(["BUY", "SELL"]),
            "qty": random.randint(1, 100),
            "price": random.uniform(500.0, 5000.0),
            "order_type": "MARKET",
        }
        orders.append(order)

    start = time.perf_counter()
    for i in range(0, len(orders), int(config.concurrency)):
        batch = orders[i : i + int(config.concurrency)]
        tasks = []

        for order in batch:
            try:
                gate.evaluate_order(
                    symbol=order["symbol"],
                    side=order["side"],
                    qty=order["qty"],
                    price=order["price"],
                    current_positions=dict(engine.positions),
                    current_pnl=engine.pnl,
                    peak_pnl=engine.peak_capital - engine.starting_capital,
                )
            except RiskViolationException:
                latencies_state["failed_orders"] += 1
                continue

            tasks.append(submit_order(engine, order, latencies_state))

        if tasks:
            await asyncio.gather(*tasks)

        if random.random() < float(config.chaos_feed_interrupt_pct):
            print("CHAOS: feed interrupt")
            await asyncio.sleep(0.001)

    duration = time.perf_counter() - start

    latencies = sorted(float(x) for x in latencies_state["latencies_ms"])
    p50 = _percentile(latencies, 50)
    p95 = _percentile(latencies, 95)
    p99 = _percentile(latencies, 99)
    passed = bool(p99 <= float(config.target_p99_ms))

    return LoadTestResult(
        p50_ms=float(p50),
        p95_ms=float(p95),
        p99_ms=float(p99),
        total_orders=int(config.n_orders),
        failed_orders=int(latencies_state["failed_orders"]),
        duration_s=float(duration),
        passed=passed,
    )


def print_report(result: LoadTestResult) -> None:
    print("Load Test Report")
    print(f"Total orders : {result.total_orders}")
    print(f"Failed       : {result.failed_orders}")
    print(f"Duration (s) : {result.duration_s:.4f}")
    print(f"p50 (ms)     : {result.p50_ms:.6f}")
    print(f"p95 (ms)     : {result.p95_ms:.6f}")
    print(f"p99 (ms)     : {result.p99_ms:.6f}")
    print(f"Target p99   : {LoadTestConfig().target_p99_ms:.6f}")
    print(f"Status       : {'PASS' if result.passed else 'FAIL'}")


if __name__ == "__main__":
    cfg = LoadTestConfig()
    res = asyncio.run(run_load_test(cfg))
    print_report(res)
    sys.exit(0 if res.passed else 1)
