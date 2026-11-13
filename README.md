# AlphaCore

[![CI](https://github.com/sohamsssssssssssssssss/alphacore/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/sohamsssssssssssssssss/alphacore/actions/workflows/ci.yml)

![Python 3.11](https://img.shields.io/badge/Python-3.11-blue)
![C++20](https://img.shields.io/badge/C%2B%2B-20-00599C)
![MIT License](https://img.shields.io/badge/License-MIT-green)

AlphaCore is a solo research project on NSE equities with three parts:

1. **A C++20 matching engine**: flat-array price map, lock-free MPSC queue, primary–backup replication and a pybind11 bridge to Python.
2. **Formal verification**: bounded TLA+ models of the queue, replication, matching and order-book logic, checked with TLC.
3. **A signal research program**: nine experiments on NIFTY 50 daily data with pre-committed protocols and stationary-bootstrap confidence intervals. **Frozen-data v2 reruns do not establish a statistically significant, cost-surviving edge.**

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

**Benchmarks** ([measured record](engine/benchmarks/RESULTS.md)): Apple M5,
macOS 27.2 arm64, Apple Clang 21.0.0 (clang-2100.4.1.1), Release build,
2026-11-12 21:19:27 UTC. These measure different operations and workloads;
no like-for-like speedup ratio is claimed.

| Benchmark | What it measures | Measured result |
|---|---|---:|
| `engine/benchmarks/flat_price_map_bench.cpp` | `FlatPriceMap` insert, 1M random-priced inserts | 7.54 ns/op |
| `engine/legacy/benchmarks/bench.cpp` | Legacy `OrderBook::add_order`, 1M orders | 55.4124 ns/op |

**Earlier run:** the [status report](ALPHACORE_STATUS_REPORT.md) recorded
4.40–5.85 ns/op for flat-map insert and 44.89 ns/op for legacy add-order.
Those earlier-run figures are historical, not the measurements in this table.

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
| `PrimaryBackup.tla` | fenced 2-node replication, partitions/loss/restart, N=6, HeartbeatLoss=2, MaxMsgs=3 (local run 2026-11-13) | 526,142,487 | 65,620,528 | TypeInv, SinglePrimaryPerEpoch, NoStaleApply, CommittedDataSafe |

## Signal research

Experiments 3–8 and the exploratory K=12 basket have been rerun on a
[hash-frozen snapshot](data_snapshots/2026-11/MANIFEST.json). Every Sharpe is
reported under two conventions, each point paired with a stationary-bootstrap
CI in the same convention: zero-rf and excess-return (annual rf=0.065). The
headline uses each experiment's **primary** convention. The long/short and
gap/PEAD strategies deploy 10–20% of equity and leave the rest as idle cash
earning nothing in the backtest, so they use zero-rf. The fully invested
long-only K=12 basket uses excess-return. See
[which convention applies](research/v2/SUMMARY.md#which-convention-applies).
The [metrics erratum](research/METRICS_ERRATUM.md) identifies inconsistent v1
pairs and the already-consistent exceptions. No strategy, cost model, seed or
locked configuration was tuned or reselected.

**Result: no tested configuration establishes a statistically significant,
cost-surviving edge in the v2 reruns.** Long/short K=1 on the expanded universe
has zero-rf Sharpe **-1.9426672674071759**, CI **[-3.3210896840840416, -0.33916023789201966]**.
With rf=0.065 it is -3.7785951031419356, CI [-5.172710614919728, -2.2318427709874316]
([raw result](research/v2/experiment_7_universe_49.json)). The long-only K=12
basket has excess-return Sharpe **0.6575848803769175**, CI **[-0.2336407666642999, 1.3619463317249594]**
([raw result](research/v2/k12_basket.json)), versus 0.5815 for ^NSEI and 1.0057 for
equal-weight buy-and-hold under the same convention. Its CI includes zero, and its final-63-session
ADV cost lookahead remains. Under zero-rf, which is not its primary convention,
the K12 CI is [0.5708, 1.9478]. That convention also flatters buy-and-hold
(^NSEI 1.0473, equal-weight 1.4047). Its Sharpe is not comparable to the
long/short experiments. See the [complete v2 table with both conventions, deployed fractions and limitations](research/v2/SUMMARY.md).
V1 reports/results below are historical and remain unchanged. Experiment 9 is
**not reproducible: source data no longer obtainable** under Yahoo's hourly
retention limit; no substitute window was used.

The list follows [`INTRADAY_SIGNAL_EXPERIMENT_PROTOCOL.md`](research/INTRADAY_SIGNAL_EXPERIMENT_PROTOCOL.md):

| # | Experiment | Protocol | v1 report (historical) | v2 |
|---|---|---|---|---|
| 1 | Single-symbol momentum / mean-reversion / OFI | selection rule in `backend/experiments/run_real_backtest.py` | [report](research/ALPHACORE_BACKTEST_REPORT.md) | not rerun (would reselect weights) |
| 2 | NSGA-II vs equal signal weights | [synthetic](research/EXPERIMENT_PROTOCOL.md), [real data](research/REAL_DATA_EXPERIMENT_PROTOCOL.md) | [synthetic](research/SIGNAL_WEIGHT_EXPERIMENT_REPORT.md), [real data](research/REAL_DATA_EXPERIMENT_REPORT.md) | not rerun (legacy selection drivers) |
| 3 | Cross-sectional relative strength, 5-day rebalance | [protocol](research/CROSS_SECTIONAL_EXPERIMENT_PROTOCOL.md) | [report](research/CROSS_SECTIONAL_EXPERIMENT_REPORT.md) | [result](research/v2/experiment_3_cross_sectional.json) |
| 4 | Cross-sectional relative strength, monthly rebalance | [protocol](research/CROSS_SECTIONAL_MONTHLY_PROTOCOL.md) | [report](research/CROSS_SECTIONAL_MONTHLY_REPORT.md) | [result](research/v2/experiment_4_monthly.json) |
| 5–6 | Overnight gap reversal; post-earnings drift (PEAD) | [protocol](research/OVERNIGHT_GAP_EXPERIMENT_PROTOCOL.md) | [report](research/OVERNIGHT_GAP_EXPERIMENT_REPORT.md) | [gap](research/v2/experiment_5_overnight_gap.json), [PEAD](research/v2/experiment_6_pead.json) |
| 7 | Universe expansion, 5 → 49 symbols | [protocol](research/UNIVERSE_EXPANSION_EXPERIMENT_PROTOCOL.md) | [report](research/UNIVERSE_EXPANSION_EXPERIMENT_REPORT.md) | [5](research/v2/experiment_7_universe_5.json), [49](research/v2/experiment_7_universe_49.json) |
| 8 | Position-count expansion, K = 1 / 5 / 10 | [protocol](research/K_EXPANSION_EXPERIMENT_PROTOCOL.md) | [report](research/K_EXPANSION_EXPERIMENT_REPORT.md) | [K1](research/v2/experiment_8_k1.json), [K5](research/v2/experiment_8_k5.json), [K10](research/v2/experiment_8_k10.json) |
| 9 | Same signal on 60-minute bars | [protocol](research/INTRADAY_SIGNAL_EXPERIMENT_PROTOCOL.md) | [report](research/INTRADAY_SIGNAL_EXPERIMENT_REPORT.md) | [unavailable](research/v2/experiment_9_hourly.json) |
| 10 | K=12 monthly top-quartile basket, lookback 21 | [exploratory, not pre-registered](research/K12_BASKET_HYPOTHESIS.md) | [provenance audit; raw result missing, selection bias](research/K12_BASKET_PROVENANCE.md) | [result](research/v2/k12_basket.json) |

V1 JSONs remain alongside historical reports; new outputs and raw returns are confined to `research/v2/`.

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
- **Verification found and fixed a replication fencing bug:** TLC showed stale-local-epoch promotion could leave two primaries in one epoch, and a C++ regression reproduced it. Promotion is now fenced with node-owned epochs and stale-epoch rejection, checked by TLC and C++ tests. Two nodes have no quorum: both can still be primary across a partition (in different epochs), and the epoch is not persisted across restarts. See [REPLICATION_FINDING.md](specs/REPLICATION_FINDING.md).
- **ITCH gateway:** Linux-only (`epoll`/`sendmsg`). On macOS, `gateway_test` runs a stub.
- **Benchmarks:** `benchmarks/results.md` is a **legacy HTTP-layer load test run on Python 3.14**. It measures the FastAPI layer, not the engine, and is not used for any claim here.

## Tests

Phase 2 baseline counts, before the Phase 2B metrics/snapshot changes (2026-11-13):

| Environment | Passed | Skipped | Deselected |
|---|---:|---:|---:|
| Local macOS, `make py-test` (built bridge and fetched daily CSVs) | 1064 | 19 | 1 |
| [Initial Linux backend CI](https://github.com/sohamsssssssssssssssss/alphacore/actions/runs/43310349447/job/131504486823) | 1018 | 15 | 0 |

Both runs emitted two numerical-precision warnings. CI skips four harness tests
requiring local NIFTY50 CSVs, six existing live-Postgres tests and five optional
bridge modules requiring `alphacore_cpp`. The local run exercises the bridge
but its 19 existing skips include five ITCH subprocess checks that skip on
SIGABRT; those parser cases are not validated. The throughput benchmark keeps
its original threshold and is excluded with `-m "not benchmark"`.

Repository-root collection before the final basket-summary self-check succeeded: **1028 tests collected**, with five
optional bridge modules skipped. C++ Release and TSan tests pass,
including `split_brain_counterexample` and `fencing_test`; see [the finding](specs/REPLICATION_FINDING.md).

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
  && ./split_brain_counterexample && ./fencing_test \
  && OB_FAULT_POOL_EXHAUSTION=1 OB_FAULT_QUEUE_FULL=1 ./fault_test)

# ThreadSanitizer build
cmake -S engine -B engine/build_tsan -DALPHACORE_TSAN=ON
cmake --build engine/build_tsan --target mpsc_tsan_test fencing_tsan_test
./engine/build_tsan/mpsc_tsan_test && ./engine/build_tsan/fencing_tsan_test

# TLA+ (tla2tools v1.7.4)
cd specs/tla
java -cp /path/to/tla2tools.jar tlc2.TLC MpscQueue.tla -config MpscQueue.cfg -deadlock
java -cp /path/to/tla2tools.jar tlc2.TLC PrimaryBackup.tla -config PrimaryBackup.cfg -deadlock
cd ../tla_engine_models
java -Xmx8g -cp /path/to/tla2tools.jar tlc2.TLC PrimaryBackup.tla -config ModelPrimaryBackup.cfg -deadlock -workers auto
cd ../..

# Dashboard
cd frontend && npm ci && npm run build
```

## License

MIT

## Reproduction

Use Python 3.11, backend dependencies, `pybind11==3.0.1`, and
`pytest pytest-asyncio httpx hypothesis`; CMake, a C++20 compiler, Java and curl
are required for engine/model checks.

```sh
make fetch-data     # first recovery, or hash verification of existing frozen files
make experiments    # locked experiments 3–8 and K12 -> research/v2/
make all            # builds/tests/benchmarks/passing TLA models, snapshot verification, v2 runs
```

The committed [manifest](data_snapshots/2026-11/MANIFEST.json) records per-file
hashes, rows, date bounds, timestamps and provider version. All snapshot CSVs
stay gitignored. Existing payloads are never refetched; missing payloads are
accepted only if recovered bytes match the committed hash. If Yahoo revisions
prevent recovery, the command fails rather than changing the manifest.
The stock/index window is 2020-08-14 through 2026-08-13; each experiment uses
its original documented sub-window and calendar holdout. The original v1
CSV snapshot is still missing. Hourly experiment 9 is not substituted.

`make experiments` verifies the snapshot, uses the original backtester classes
and locked v1 parameters, and writes raw returns, consistent point/CI metrics
and the [summary](research/v2/SUMMARY.md). No N search or NSGA-II driver runs.
All v1 research files are checked unchanged. K12 benchmarks are descriptive
buy-and-hold at the same observation dates; the known cost lookahead and the
original PEAD return-basis limitation remain documented.

Individual targets remain `engine-build`, `engine-test`, `engine-bench`,
`tla`, `py-test`, `fetch-data` and `experiments`. Use `PYTHON=/path/to/python3.11`
and `JAVA=/path/to/java` where needed. Engine tests and benchmarks require
`engine-build` first. Build artifacts stay under `.reproduce/`; benchmark
measurements append to `engine/benchmarks/RESULTS.md`. The v1 scratch-comparison
helper remains in `scripts/reproduce.py` for historical audit, while the
standard experiments target runs v2.

The original failing replication model and its trace are kept, not run, under
`specs/tla_engine_models/history/`; the fenced model and the former C++
counterexample now run with the passing checks. See
[REPLICATION_FINDING.md](specs/REPLICATION_FINDING.md). Other large TLA model
configurations are not claimed checked.
