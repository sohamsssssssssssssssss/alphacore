# Recorded local benchmark runs

## 2026-11-12T21:19:27.654403+00:00

Machine: macOS-27.2-arm64-arm-64bit / Apple M5.
Compiler: Apple clang version 21.0.0 (clang-2100.4.1.1). Build: Release; flat map uses CMake flags; legacy uses `-O3 -DNDEBUG -std=c++20`.

| Benchmark | ns/op |
|---|---:|
| FlatPriceMap insert (1M) | 7.54 |
| Legacy OrderBook add_order (1M) | 55.4124 |

Different operations/workloads; these are not a like-for-like speedup measurement.
