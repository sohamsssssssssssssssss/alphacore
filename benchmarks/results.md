# AlphaCore Benchmark Results

Run at: 2026-05-14 10:21:25 

## System Info
- Python: `3.14.3 (v3.14.3:323c59a5e34, Feb  3 2026, 11:41:37) [Clang 16.0.0 (clang-1600.0.26.6)]`
- OS: `Darwin 25.4.0 (Darwin Kernel Version 25.4.0: Thu Mar 19 19:33:43 PDT 2026; root:xnu-12377.101.15~1/RELEASE_ARM64_T8142)`
- CPU cores: `10`

## Per-endpoint latency
| Endpoint | p50 (ms) | p95 (ms) | p99 (ms) | min | max | mean | req/sec | error rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| /api/health | 67.31 | 84.67 | 93.40 | 27.27 | 95.72 | 69.33 | 5157.23 | 0.00% |
| /api/orderbook/RELIANCE | 24.26 | 28.32 | 28.92 | 7.83 | 29.88 | 20.12 | 14616.71 | 0.00% |
| /api/orderbook/TCS | 23.35 | 27.19 | 28.34 | 8.51 | 28.71 | 19.30 | 15288.36 | 0.00% |
| /api/detections/icebergs | 227.34 | 396.81 | 410.57 | 36.62 | 410.64 | 229.72 | 1192.52 | 0.00% |
| /api/detections/spoof | 251.66 | 436.86 | 452.46 | 46.40 | 455.83 | 252.43 | 1074.56 | 0.00% |
| /api/detections/summary | 347.22 | 465.78 | 473.31 | 53.09 | 476.34 | 332.70 | 1044.08 | 0.00% |
| /api/flow/RELIANCE | 26.59 | 30.82 | 31.80 | 7.60 | 31.94 | 22.26 | 13589.74 | 0.00% |
| /api/heatmap/RELIANCE | 112.16 | 182.53 | 187.62 | 32.95 | 188.43 | 112.33 | 2544.28 | 0.00% |
| /api/narrative/current | 54.03 | 78.27 | 80.01 | 27.11 | 80.11 | 54.23 | 5589.92 | 0.00% |

## Sustained throughput
| Endpoint | Rounds | Requests/Round | Total Requests | Total Time (s) | Overall req/sec |
| --- | --- | --- | --- | --- | --- |
| /api/orderbook/RELIANCE | 5 | 500 | 2500 | 0.19 | 13072.82 |

## WebSocket results
| Status | Successful Connections | Mean Connect (ms) | Mean Time-to-First-Message (ms) | Errors |
| --- | --- | --- | --- | --- |
| WS endpoint not active | 0/100 | 0.00 | 0.00 | None |

## Detection engine latency
| p50 (ms) | p95 (ms) | p99 (ms) | min | max | mean | req/sec | error rate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 162.20 | 202.72 | 203.93 | 53.15 | 204.73 | 155.77 | 973.31 | 0.00% |

## AlphaCore vs Standard OME
| Metric | AlphaCore | Standard OME | AlphaCore Advantage |
| --- | --- | --- | --- |
| p50 latency (orderbook endpoint) | 24.26 ms | ~8 ms | 0.33x |
| p99 latency (orderbook endpoint) | 28.92 ms | ~45 ms | 1.56x |
| Throughput (req/sec, sustained) | 13072.82 | ~400 | 32.68x |
| Detection engines | ✅ | ❌ | ✅ |
| Iceberg detection | ✅ | ❌ | ✅ |
| Spoof detection | ✅ | ❌ | ✅ |
| Flow analysis | ✅ | ❌ | ✅ |
| Liquidity heatmap | ✅ | ❌ | ✅ |
| Narrative signals | ✅ | ❌ | ✅ |
| WebSocket streaming | ❌ | ❌ | ❌ |
| Real-time DB persistence | ✅ | ❌ | ✅ |

## Summary
- Best performing endpoint: `/api/orderbook/TCS` at `23.35ms` p50
- Worst performing endpoint: `/api/detections/summary` at `473.31ms` p99
- Overall system throughput: `13072.82` req/sec sustained
- WebSocket: `0/100` connections successful
- Verdict: AlphaCore outperforms standard OME on `2` of `3` metrics
