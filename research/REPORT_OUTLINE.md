# Technical report outline (draft)

**Working title:** AlphaCore: A Formally Verified Matching Engine and a Reproducible Negative Result for Momentum-Style Signals on NSE Equities

**Length:** about 8 pages. Every table and figure is generated from files in this repository.

1. **Summary** (half a page). What was built, what was tested, and the result: no cost-surviving edge. One paragraph on why a negative result is still useful.
2. **System** (1 page). The engine's parts and an architecture diagram, plus measured benchmarks with machine details and no speed comparisons.
3. **Formal verification** (1.5 pages). What the TLA+ models check and their limits. The split-brain bug: the trace, the C++ lines involved, and the failing test. The first fix the model checker rejected, then the fix that passed across 65.6 million states. The shutdown race that only Linux's thread sanitizer caught.
4. **Research method** (1 page). Protocols written before testing, the cost model, stationary-bootstrap intervals, the frozen data snapshot with checksums, and the two Sharpe conventions.
5. **Results** (2 pages). One table and one chart of all experiments with their intervals. Eight configurations are significantly negative; post-earnings drift is inconclusive. Cost drag grows as positions are added. The K=12 basket does worse than holding every stock equally.
6. **Errors found in our own work** (1 page). The mismatched Sharpe and interval, results that did not reproduce, the unverifiable 0.6610 figure, and the future-liquidity cost leak.
7. **Limitations** (half a page). Free Yahoo data, no real fills, detectors tested only on synthetic data, two-node replication with no restart safety, a single market period.
8. **Reproduction** (half a page). The one-command reproduction, and what cannot be reproduced and why.

**Open decisions:** outline approval; LaTeX (generated from repo files) vs. a hand-edited document.
