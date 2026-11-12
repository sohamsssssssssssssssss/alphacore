# AlphaCore

[![CI](https://github.com/sohamsssssssssssssssss/alphacore/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/sohamsssssssssssssssss/alphacore/actions/workflows/ci.yml)

![Python 3.11](https://img.shields.io/badge/Python-3.11-blue)
![C++20](https://img.shields.io/badge/C%2B%2B-20-00599C)
![MIT License](https://img.shields.io/badge/License-MIT-green)

AlphaCore is a solo research project on NSE equities with three parts:

1. **A C++20 matching engine**: flat-array price map, lock-free MPSC queue, primary–backup replication and a pybind11 bridge to Python.
2. **Formal verification**: bounded TLA+ models of the queue, replication, matching and order-book logic, checked with TLC.
3. **A signal research program**: nine experiments on NIFTY 50 daily data with pre-committed protocols and stationary-bootstrap confidence intervals. **The result is negative: no configuration produced a cost-surviving edge.**

A Python backend (FastAPI, order-book detectors, backtester, paper-trading harness) and a React/Vite dashboard sit around these parts.

Every number below links to the file that produced it. The full honest-status audit is in [`ALPHACORE_STATUS_REPORT.md`](ALPHACORE_STATUS_REPORT.md).

## Repository layout

| Path | Contents |
|---|---|
| `engine/` | C++ matching engine, tests, benchmarks, pybind11 bindings (`CMakeLists.txt`) |
| `engine/legacy/` | Older `std::map`-based order book and its benchmark |
| `specs/tla/` | TLA+ specs checked in CI (MpscQueue, PrimaryBackup, plus KillSwitch, DetectionQueue, OrderBook) |
| `specs/tla_engine_models/` | A second, differently-configured set of TLA+ models (MpscQueue, MatchingEngine, OrderBook, PrimaryBackup) |
| `backend/` | Python: detectors, signals, backtester, experiments, paper-trading harness, tests |
| `frontend/` | React/Vite dashboard |
| `research/` | Experiment protocols, reports and result JSONs |
| `benchmarks/` | Legacy HTTP-layer load test (see below) |

## Matching engine (C++)

Components in `engine/src/`: `FlatPriceMap` (array-indexed price levels), `MatchingEngine` with worker threads, a lock-free MPSC ring buffer, an object pool, primary–backup replication with heartbeats, an ITCH parser/gateway and pybind11 bindings (`alphacore_cpp`).

**Benchmarks** (Release build; source: [`ALPHACORE_STATUS_REPORT.md`](ALPHACORE_STATUS_REPORT.md), "Benchmark Numbers"). These are two different benchmarks and are not comparable to each other:

| Benchmark | What it measures | Result |
|---|---|---:|
| `engine/benchmarks/flat_price_map_bench.cpp` | `FlatPriceMap` insert, 1M random-priced inserts | 4.40–5.85 ns/op (run-to-run variance) |
| `engine/legacy/benchmarks/bench.cpp` | `OrderBook::add_order` on the older `std::map` book, 1M orders | 44.89 ns/op |

**Tests:** `engine_test`, `replication_test`, `gateway_test`, `fault_test`, `ha_chaos_test`, `deterministic_replay_test`, plus `mpsc_tsan_test` built under ThreadSanitizer. Linux CI passes these Release tests and the TSan test; the macOS gateway test uses a stub.

## Formal verification (TLA+)

All results are from **bounded / reduced models**: small constants, checked exhaustively by TLC. They are not proofs about the unbounded system.

Specs in `specs/tla/`, checked in CI with tla2tools v1.7.4 (source: [`research/ALPHACORE_CPP_UPGRADE_REPORT.md`](research/ALPHACORE_CPP_UPGRADE_REPORT.md), Part 3):

| Spec | Model | States generated | Distinct states | Invariants |
|---|---|---:|---:|---|
| `MpscQueue.tla` | 2 producers, 1 consumer, Capacity=4 | 1,243,889 | 327,308 | NoTornRead, ItemsInOutAreFromEnqueue, NoDuplicates, FullQueueBackpressure |
| `PrimaryBackup.tla` | 2 nodes, epoch fencing, network faults | 280,331 | 29,500 | AtMostOneLeader, ActiveEpochUnique, NoSplitBrain, EpochFencing, PromotionOnlyOnTimeout, CommittedDataSafe |

Models in `specs/tla_engine_models/` (source: [`ALPHACORE_STATUS_REPORT.md`](ALPHACORE_STATUS_REPORT.md), "TLA+ Formal Verification"):

| Spec | Model | States generated | Distinct states | Invariants |
|---|---|---:|---:|---|
| `MpscQueue.tla` | bounded | 421 | 289 | TypeInv, NeverOverflow, Linearizability, NoDataLoss |
| `MatchingEngine.tla` | reduced model | 24,445 | 22,177 | PriceTimePriority, NoCrossTrading, NoOrderLoss |
| `OrderBook.tla` | reduced model (3 prices, 3 order IDs, 2 quantities) | 2,901,043 | 1,786,483 | NoGhostOrders, QuantityConservation |

## Signal research

Nine experiments on NIFTY 50 data. Each was run against a protocol (or selection rule) committed before the test period was evaluated. Confidence intervals come from a stationary bootstrap (Politis–Romano). The cost model is in `backend/engines/cost_model.py`.

**Result: no configuration produced a cost-surviving, statistically significant edge.** The least-bad configuration was 49 symbols, K=1 (one long and one short), a 21-trading-day rebalance, daily bars: **Sharpe −1.57, 95% CI [−3.14, +0.05]**. Sources: [`UNIVERSE_EXPANSION_EXPERIMENT_REPORT.md`](research/UNIVERSE_EXPANSION_EXPERIMENT_REPORT.md), [`K_EXPANSION_EXPERIMENT_REPORT.md`](research/K_EXPANSION_EXPERIMENT_REPORT.md).

The list follows [`INTRADAY_SIGNAL_EXPERIMENT_PROTOCOL.md`](research/INTRADAY_SIGNAL_EXPERIMENT_PROTOCOL.md):

| # | Experiment | Protocol | Report |
|---|---|---|---|
| 1 | Single-symbol momentum / mean-reversion / OFI | selection rule in `backend/experiments/run_real_backtest.py` | [report](research/ALPHACORE_BACKTEST_REPORT.md) |
| 2 | NSGA-II vs equal signal weights | [synthetic](research/EXPERIMENT_PROTOCOL.md), [real data](research/REAL_DATA_EXPERIMENT_PROTOCOL.md) | [synthetic](research/SIGNAL_WEIGHT_EXPERIMENT_REPORT.md), [real data](research/REAL_DATA_EXPERIMENT_REPORT.md) |
| 3 | Cross-sectional relative strength, 5-day rebalance | [protocol](research/CROSS_SECTIONAL_EXPERIMENT_PROTOCOL.md) | [report](research/CROSS_SECTIONAL_EXPERIMENT_REPORT.md) |
| 4 | Cross-sectional relative strength, monthly rebalance | [protocol](research/CROSS_SECTIONAL_MONTHLY_PROTOCOL.md) | [report](research/CROSS_SECTIONAL_MONTHLY_REPORT.md) |
| 5–6 | Overnight gap reversal; post-earnings drift (PEAD) | [protocol](research/OVERNIGHT_GAP_EXPERIMENT_PROTOCOL.md) | [report](research/OVERNIGHT_GAP_EXPERIMENT_REPORT.md) |
| 7 | Universe expansion, 5 → 49 symbols | [protocol](research/UNIVERSE_EXPANSION_EXPERIMENT_PROTOCOL.md) | [report](research/UNIVERSE_EXPANSION_EXPERIMENT_REPORT.md) |
| 8 | Position-count expansion, K = 1 / 5 / 10 | [protocol](research/K_EXPANSION_EXPERIMENT_PROTOCOL.md) | [report](research/K_EXPANSION_EXPERIMENT_REPORT.md) |
| 9 | Same signal on 60-minute bars | [protocol](research/INTRADAY_SIGNAL_EXPERIMENT_PROTOCOL.md) | [report](research/INTRADAY_SIGNAL_EXPERIMENT_REPORT.md) |
| 10 | K=12 monthly top-quartile basket, lookback 21 | [exploratory, not pre-registered](research/K12_BASKET_HYPOTHESIS.md) | [provenance audit; raw result missing, selection bias](research/K12_BASKET_PROVENANCE.md) |

Result JSONs sit next to the reports in `research/`.

## Data

The imported K=12 basket is **exploratory, not pre-registered**: its quoted result has no recoverable raw return series, its history overlaps earlier failed experiments, and it needs fresh out-of-sample validation. See the [provenance audit](research/K12_BASKET_PROVENANCE.md).

Historical data is daily OHLCV for NIFTY 50 symbols, pulled with `yfinance` (`backend/experiments/fetch_nifty50_data.py`); experiment 9 used 60-minute bars, also from `yfinance`. The CSVs are gitignored and must be fetched locally. The backend's paper session polls `yfinance` on a schedule. **There is no live NSE feed or WebSocket market-data stream** (`ALPHACORE_STATUS_REPORT.md`).

## Order-book detectors

The backend includes a rule-based iceberg detector (repeated refills at one price level, `backend/engines/iceberg_detector.py`) and a spoof detector (a score built from cancel speed, fill ratio, price impact, counter-trade and repeat sub-scores, `backend/engines/spoof_detector.py`). **They have been exercised only on synthetic data**: hand-built fixtures and Hypothesis-generated order books in `backend/tests/`. No evaluation on real or labelled market data exists, so no accuracy, precision or recall is claimed.

## Paper trading

[`backend/paper_trading/`](backend/paper_trading/) holds the locked K=1 Upstox sandbox harness. A separate K=12 basket harness in a local export submitted sandbox orders on 2026-08-15; the inspected history remained `open pending` with zero filled quantity. See the raw evidence and source paths in the [2026-11-13 addendum](PAPER_TRADING_LOG.md#addendum-2026-11-13). This does not establish that the K=1 scheduler ran. **No confirmed fills were found**, so execution costs remain unvalidated.

## Limitations

From [`ALPHACORE_STATUS_REPORT.md`](ALPHACORE_STATUS_REPORT.md):

- **RL:** the "multi-agent" PPO code is single-agent (independent copies, no interaction) and runs on synthetic data only.
- **NSGA-II:** an earlier Sharpe 1.70 / Calmar 3.33 figure was **not reproduced**; its origin is unclear.
- **Fault injection:** only 2 of the 10 fault types in `engine/src/fault_injector.hpp` (`POOL_EXHAUSTION`, `QUEUE_FULL`) are wired into production code.
- **ITCH gateway:** Linux-only (`epoll`/`sendmsg`). On macOS, `gateway_test` runs a stub.
- **Benchmarks:** `benchmarks/results.md` is a **legacy HTTP-layer load test run on Python 3.14**. It measures the FastAPI layer, not the engine, and is not used for any claim here.

## Tests

Python 3.11 non-benchmark suite (`cd backend && python3.11 -m pytest tests/ -q -m "not benchmark"`):

| Environment | Passed | Skipped | Errors |
|---|---:|---:|---:|
| Local macOS, `DATABASE_URL` unset | 961 | 15 | 0 |
| [Linux CI](https://github.com/sohamsssssssssssssssss/alphacore/actions/runs/43288458290) | 961 | 15 | 0 |

Both runs emitted two numerical-precision warnings. The skips are four harness tests requiring local NIFTY50 CSVs, six existing live-Postgres tests, and five bridge modules requiring `alphacore_cpp` on `sys.path`. The Python bridge suites are not validated by these runs; C++ executables run separately in CI. The throughput benchmark keeps its original threshold and is excluded from CI with `-m "not benchmark"`.

Plain repository-root pytest collection also succeeds with `DATABASE_URL` unset: **971 tests collected**, with five optional bridge modules skipped.

## Setup

These are the commands used to verify this README (macOS, Python 3.11, CMake, Node):

```bash
# Python backend + tests
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
pip install pytest pytest-asyncio httpx hypothesis
cd backend && python3.11 -m pytest tests/ -q -m "not benchmark" && cd ..

# C++ engine + tests
cmake -S engine -B engine/build -DCMAKE_BUILD_TYPE=Release
cmake --build engine/build -j8
(cd engine/build && ./engine_test && ./replication_test && ./gateway_test \
  && ./ha_chaos_test && ./deterministic_replay_test \
  && OB_FAULT_POOL_EXHAUSTION=1 OB_FAULT_QUEUE_FULL=1 ./fault_test)

# ThreadSanitizer build
cmake -S engine -B engine/build_tsan -DALPHACORE_TSAN=ON
cmake --build engine/build_tsan --target mpsc_tsan_test && ./engine/build_tsan/mpsc_tsan_test

# TLA+ (tla2tools v1.7.4)
cd specs/tla
java -cp /path/to/tla2tools.jar tlc2.TLC MpscQueue.tla -config MpscQueue.cfg -deadlock
java -cp /path/to/tla2tools.jar tlc2.TLC PrimaryBackup.tla -config PrimaryBackup.cfg -deadlock
cd ../..

# Dashboard
cd frontend && npm ci && npm run build
```

## License

MIT
