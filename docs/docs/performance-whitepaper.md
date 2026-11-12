# AlphaCore: Matching Engine Performance Notes

## Abstract
AlphaCore is designed for deterministic matching and feature extraction under Indian equity microstructure constraints.

## Methodology
Benchmarks were collected on Apple Silicon M-series hardware. Timing is measured with a high-resolution counter path and a chrono fallback when `rdtsc`-style counters are unavailable.

## Results

Numbers below are taken from `ALPHACORE_STATUS_REPORT.md` (Release build). They are two different benchmarks and should not be compared to each other.

| Benchmark | Source | Result |
|---|---|---:|
| `FlatPriceMap` insert, 1M random-priced inserts | `engine/benchmarks/flat_price_map_bench.cpp` | 4.40–5.85 ns/op (run-to-run variance) |
| `OrderBook::add_order` (older `std::map` book), 1M orders | `engine/legacy/benchmarks/bench.cpp` | 44.89 ns/op |

## Design Decisions
- Preallocated contiguous `PriceLevel` vector.
- Active bitmap for branch-light occupancy checks.
- Dense order index for cache-local ID lookup.
- `unit_tick` fast path for common price-step arithmetic.
- Split bid/ask cache lines to reduce false sharing.

## TLA+ Verification
Bounded / reduced-model checks are recorded in `ALPHACORE_STATUS_REPORT.md` (TLA+ section): MpscQueue (bounded), MatchingEngine (reduced model), OrderBook (reduced model). These are small configurations, not exhaustive proofs of the full engine.

## Conclusion
AlphaCore uses cache-aware data layout, a lock-free MPSC queue, and bounded TLA+ model checking of its queue, matching and order-book logic.
