# Cross-Sectional Relative Strength — Monthly Rebalancing Protocol

**Date:** July 30, 2026 — 19:00 IST  
**Status:** **PRE-COMMITTED** — written before any test-period evaluation is run  
**Predecessor experiments:**
- `CROSS_SECTIONAL_EXPERIMENT_PROTOCOL.md` (original 5-day rebalance protocol)
- `CROSS_SECTIONAL_EXPERIMENT_REPORT.md` (original report + diagnostic addendum)
- `backend/experiments/cross_sectional_diagnostic.py` (MTM bug fix + diagnostics)

---

## Why This Test Exists

The diagnostic pass on the original every-5-days cross-sectional relative strength experiment found:

1. The signal has genuine directional skill (LONG on winners 61%, SHORT on losers 72%)
2. A naive buy-and-hold of the initial picks was gross-profitable (+₹1,503)
3. But rebalancing every 5 days produced **243% cost drag**, with **98.6% of costs** from whipsaw/turnover

The question: does reducing rebalance frequency by ~4× (from every 5 days to monthly) let the signal's real edge survive transaction costs?

---

## Pre-Committed Parameter Choices

### Only one parameter changes from the original experiment:

| Parameter | Original (5-day) | This Test (Monthly) |
|-----------|-----------------|---------------------|
| **Rebalance frequency** | Every 5 trading days | **Every 21 trading days** (≈ monthly) |
| N (lookback window) | 20 (unchanged) | **20 (unchanged)** |
| K (long/short legs) | 1 (unchanged) | **1 (unchanged)** |
| Cost model | `CostModel()` default | **Same** |
| Train/test split | Chronological 70/30 | **Same** |
| MTM logic | Fixed (diagnostic) | **Fixed (diagnostic)** |
| Position sizing | 10% per leg | **Same** |
| Initial capital | ₹100,000 | **Same** |

### Why 21 trading days?

- 21 trading days ≈ 1 calendar month — a natural, standard rebalance horizon
- Reduces turnover by roughly 4× compared to every 5 days (from ~71 rebalance events to ~17-18)
- Long enough to meaningfully reduce cost drag, short enough to still capture cross-sectional changes
- This is a single pre-committed choice, not a sweep

---

## Primary Metric

**Sharpe ratio of the long/short basket's daily returns** (net of all costs, annualized, 252-day, excess over 6.5% RFR) — identical to the original experiment.

---

## Bootstrap Configuration

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Method | Stationary bootstrap (Politis-Romano) | Same as all prior experiments |
| Resamples | 2,000 | Same as all prior experiments |
| **Block length** | **21 trading days** | Matches the new 21-day rebalance cycle |
| Confidence | 95% | Same |
| Seed | 2026 | Same |

**Block length justification:** With monthly rebalancing, the autocorrelation structure changes from the 5-day case. A block length of 21 trading days (one full rebalance cycle) captures the natural dependency between returns within the same rebalance period. This is appropriately conservative for ∼17-18 rebalance events.

---

## Anticipated Limitations (Pre-Committed)

1. **Very small number of rebalance events:** With ∼372 test days and 21-day rebalancing, we expect roughly **17-18 rebalance events** total. This is a small sample — bootstrap confidence intervals will be wide, and statistical power is limited regardless of the point estimate.

2. **5-symbol universe unchanged:** The same 5-symbol limitation applies (see original report for full discussion).

3. **Single test of a single frequency:** This is one test of one rebalance frequency (monthly). If the result is positive but not significant, it doesn't prove monthly is the answer — it just suggests the direction is worth exploring with more data or a larger universe.

4. **Cost model unchanged:** Short-selling borrow costs are still not modeled (same as original).

---

## What Would Invalidate This Run

- Testing multiple rebalance frequencies and picking whichever looks best (sweeping)
- Changing N, K, or any other parameter from the original experiment
- Using a different train/test split
- Modifying the cost model
- Reintroducing the MTM bug (the fixed backtester must be used)

---

*This protocol was written before any test-period results were computed. The only variable changed from the original experiment is the rebalance frequency.*
