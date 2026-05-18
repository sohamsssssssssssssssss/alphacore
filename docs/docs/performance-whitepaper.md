# AlphaCore: Sub-10ns Order Matching for Indian Equity Markets

## Abstract
AlphaCore is designed for deterministic matching and feature extraction under Indian equity microstructure constraints, targeting sustained sub-10ns core-path operations where feasible.

## Methodology
Benchmarks were collected on Apple Silicon M-series hardware. Timing is measured with a high-resolution counter path and a chrono fallback when `rdtsc`-style counters are unavailable.

## Results

| Benchmark | AlphaCore | Baseline | Improvement |
|---|---:|---:|---:|
| FlatPriceMap lookup/update | 7.77 ns | Atharva OME 39.8 ns | 5.1x faster |
| ITCH parser throughput | 5.63 ns/msg | CppTrader 24 ns/msg | 4.3x faster |
| MPSC queue throughput | 10.1M ops/s | Target 5M ops/s | 2.0x target |

## Design Decisions
- Preallocated contiguous `PriceLevel` vector.
- Active bitmap for branch-light occupancy checks.
- Dense order index for cache-local ID lookup.
- `unit_tick` fast path for common price-step arithmetic.
- Split bid/ask cache lines to reduce false sharing.

## TLA+ Verification
Formal specs were model checked across 1M+ states.
- 3 specifications were validated for safety/liveness and fault transitions.

## Conclusion
AlphaCore meets its low-latency engineering targets through cache-aware data layout, lock-free concurrency primitives, and formal verification in critical correctness paths.
