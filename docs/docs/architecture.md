# Architecture

## System Overview
AlphaCore is built as three tightly integrated layers:
1. C++ core for deterministic low-latency matching and ingest.
2. Python intelligence for alpha generation, regime detection, and model orchestration.
3. Live execution for paper/live brokerage routing with hard risk controls.

## C++ Matching Core
The C++ core is optimized for predictable microstructure workloads:
- `FlatPriceMap` with O(1) level access.
- `ObjectPool` allocation strategy to avoid runtime heap churn.
- MPSC lock-free queues for high-throughput cross-thread handoff.
- Binary ITCH parser optimized for fixed-width decoding.
- Epoll-based TCP gateway for low-overhead market data ingress.
- HA replication pipeline for resilient state continuity.
- TLA+ specs used to validate safety/liveness properties under fault paths.

## Python Intelligence Layer
The intelligence layer converts order book state into tradeable decisions:
- 11 alpha factors including `iceberg_pressure` and `spoof_reversal`.
- HMM regime classifier for market-state segmentation.
- PPO agent for policy-based adaptive behavior.
- NSGA-II optimizer for multi-objective tuning.
- 42 order-book feature vector per snapshot.
- 4-model ensemble for robust signal fusion.

## Live Execution Layer
Execution bridges model intent to controlled fills:
- `PaperTradingEngine` for deterministic simulation and dry-run validation.
- `KiteBroker` for Zerodha routing.
- `RiskGate` enforcing 5 hard pre-trade checks.
- `AlphaStrategy` as pluggable strategy implementation.
- EOD flatten scheduler to neutralize positions at close.
