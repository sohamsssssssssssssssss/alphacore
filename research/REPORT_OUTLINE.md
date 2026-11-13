# Technical report outline (v2)

**Working title:** AlphaCore: A Model-Checked Replication Protocol and Matching Engine, and a Reproducible Negative Result for Momentum-Style Signals on NSE Equities

**Length:** about 8 pages, engineering-led (roughly 60% engineering, 40% research). Every table and figure is generated from files in this repository.

**Wording rule:** say "model-checked" or "bounded model checking", never "formally verified". The TLA+ results are exhaustive checks of small hand-written models, not proofs about the C++ code.

1. **Summary** (half a page). What was built, what was checked, and the two findings: a replication bug found and fixed through model checking, and no cost-surviving trading edge.
2. **System** (1 page). The engine's parts and an architecture diagram, plus measured benchmarks with machine details and no speed comparisons. Source: `engine/benchmarks/RESULTS.md`.
3. **Model checking and the replication bug** (2 pages).
   - What each TLA+ model checks and at what size. The matching and order-book models in CI are small (see `specs/README.md`); the large check is on replication.
   - The split-brain bug: the 4-step trace, the C++ lines involved, and the failing test. Sources: `specs/REPLICATION_FINDING.md`, `engine/tests/split_brain_counterexample.cpp`.
   - The first fix (highest seen epoch plus one), which the model checker rejected; then the fix that passed across 65.6 million distinct states (owned epochs plus stale-entry rejection). Source: `engine/tests/fencing_test.cpp`.
   - The shutdown race that only Linux's thread sanitizer caught.
   - What is not shown: the models are abstractions of the code; two nodes with no quorum can both lead during a partition; the model persists the epoch across restarts and the C++ does not.
4. **Research method** (1 page). The cost model, stationary-bootstrap intervals, the frozen data snapshot with checksums (`data_snapshots/2026-11/MANIFEST.json`), and the two Sharpe conventions. Pre-registration stated per experiment: experiments 3 to 9 have protocol files; experiment 1 has only a selection rule in code; the K=12 basket was not pre-registered.
5. **Results** (1.5 pages). One table and one chart with intervals, in four categories. Source: `research/v2/SUMMARY.md`.
   - **Significantly negative:** seven distinct long/short and gap configurations (the "Universe 49" and "K=1" rows are the same run).
   - **Inconclusive:** post-earnings drift, before fees, on 125 events.
   - **Exploratory, no edge shown:** the long-only K=12 basket. Its interval includes zero and it did not beat equal-weight buy-and-hold on point estimates (benchmarks are before costs).
   - **Not re-run:** experiments 1 and 2 (re-running would reselect weights) and experiment 9 (hourly data no longer obtainable).
   - Cost drag versus position count is reported from the v1 report only, labelled as such, unless recomputed on the frozen data.
6. **Errors found in our own work** (1 page). The Sharpe and its interval using different definitions (`research/METRICS_ERRATUM.md`); results that did not reproduce because data was not frozen; the 0.6610 figure with no raw data behind it and the future-liquidity cost leak (`research/K12_BASKET_PROVENANCE.md`).
7. **Limitations of the setup** (half a page). Kept separate from section 6. Free Yahoo data, no real fills, detectors tested only on synthetic data, a single market and period.
8. **Reproduction** (half a page). `make all` re-runs what can be re-run and exits with failure by design for the cases that cannot; list those cases and why.

**Open decision:** LaTeX (generated from repo files) vs. a hand-edited document.
