# Universe Expansion Experiment — Cross-Sectional Relative Strength on NIFTY 50

**Date:** July 31, 2026 — 00:30 IST  
**Status:** **PRE-COMMITTED** — written before any test-period evaluation results on the expanded universe were seen  
**Predecessor experiments (7 failed signal families on 5-symbol universe):**
1. Momentum, mean-reversion, OFI (single-symbol: Sharpe -11.3)  
2. NSGA-II vs equal weights (synthetic GBM: null)  
3. NSGA-II vs equal weights (real data: null — all CIs include zero)  
4. Cross-sectional relative strength, 5-day rebalance (cost drag 243%, Sharpe -7.19)  
5. Cross-sectional relative strength, monthly rebalance (cost drag 123.8%, Sharpe -4.59)  
6. Overnight gap reversal (Sharpe -6.80, cost drag 610.6%)  
7. Post-earnings-announcement drift (net -₹4,622, cost drag 454.7%)

---

## Why This Task Exists

The prior report concluded that the ONE signal family showing real directional skill (cross-sectional relative strength, 61-72% directional accuracy) was destroyed by transaction costs because the 5-symbol universe produced insufficient ranking persistence and cost averaging. This experiment tests the obvious next lever: **does expanding the universe to 50 symbols let costs average out relative to the signal's directional edge?**

---

## STEP 0 OUTCOME — Higher-Frequency Data Feasibility (Time-boxed)

- **yfinance intraday history:** Available for 5m, 15m, 30m, 60m, and 1h intervals, but history is severely limited:
  - Sub-hourly intervals (5m-60m): max ~5-7 days of historical data
  - Hourly interval: ~18 months max (tested 3mo: 434 rows for 1 symbol)
- **Verdict:** NOT suitable for meaningful backtesting. A minimum 3-month backtest window is achievable with hourly bars, but the 2021-2026 range used by all prior experiments is impossible with any yfinance intraday data.
- **Decision:** Higher-frequency data is flagged for future work with a dedicated data source (broker API, paid historical ticks). **Not pursued in this task.**

---

## Part A — Expanded Universe Definition

### 1. Target Universe

**NIFTY 50 constituents** (50 symbols) — defined in `backend/data/nifty50_symbols.py`.

### 2. Data Source

Yahoo Finance via the same yfinance-based pipeline used for the original 5 symbols. Each symbol's data is saved as `backend/data/nifty50_data/{SYMBOL}.csv`, following the same format as `backend/data/real_nse_data/`.

### 3. Exclusion Criteria (Applied before any backtest)

| Criterion | Threshold | Rationale |
|-----------|-----------|-----------|
| Minimum trading days | ≥ 850 rows (~80% of ~1,239 expected) | Excludes IPOs and delistings within the range |
| Consecutive missing data | ≤ 10 consecutive NaN days in Close | Excludes symbols with large data gaps |
| Date range coverage | ≥ 90% of target range (2021-07-30 to 2026-07-30) | Excludes symbols that don't span most of the period |

### 4. Expected Universe Size

Based on NIFTY 50 being large-cap liquid stocks with reliable yfinance coverage, target 45-50 symbols after exclusions.

---

## Part B — Cross-Sectional Relative Strength Signal

### 1. Exact Signal Definition (Reused from 5-Symbol Experiment)

| Parameter | Value | Source |
|-----------|-------|--------|
| **Lookback window N** | **20 trading days** (~1 month) | Locked in 5-symbol experiment (higher train Sharpe than N=60) |
| **K (long/short legs)** | **1 each** | Original experiment protocol |
| **Rebalance frequency** | **Every 21 trading days** (~monthly) | **Better performing of the two tested frequencies** (monthly: -4.59 vs 5-day: -7.19 on 5-symbol) |
| **Position sizing** | **10% of equity per leg**, dollar-neutral | Same as prior experiments |
| **Cost model** | **`CostModel()` default** (k=0.0015, ₹20/trade, STT 0.1% on sells) | Identical to all prior experiments |
| **Initial capital** | ₹100,000 | Same as prior experiments |

### 2. Why This Exact Definition

**No parameters are being re-tuned for the expanded universe.** The point of this test is to isolate the effect of universe size alone. Changing the signal logic at the same time would confound the result.

The monthly rebalance frequency (21 days) is chosen because on the 5-symbol universe, the 5-day rebalance had 243% cost drag vs the monthly's 123.8% — monthly was strictly less bad. If expanded-universe cost averaging is going to work, the lower-turnover version has the best chance of showing it.

### 3. Primary Metric

**Sharpe ratio** of the long/short basket's daily returns (annualized, 252 periods/year, excess over 6.5% RFR) — net of all transaction costs — over the held-out test period.

### 4. Train/Test Split

Identical to all prior experiments — chronological 70/30:

| Period | Start | End | Rows |
|--------|-------|-----|------|
| **TRAIN** | 2021-07-30 | 2025-01-29 | 867 |
| **TEST** | 2025-01-30 | 2026-07-30 | 372 |

### 5. Bootstrap CI

- **Method:** Stationary bootstrap (Politis-Romano) on daily basket returns
- **Mean block length:** **21** (matches the new monthly rebalance cycle)
- **Resamples:** 2,000
- **Seed:** 2026
- **Confidence:** 95%

---

## Part C — What Would Invalidate This Run

- Re-tuning the lookback window N, K, rebalance frequency, or position sizing on the expanded universe (must reuse exact locked parameters from the 5-symbol test).
- Changing the cost model parameters.
- Adding or removing symbols from the universe based on test-performance criteria.
- Changing the train/test split.
- Testing multiple rebalance frequencies and reporting the best one.
- Changing the exclusion criteria after seeing test results.

---

## Part D — Critical Comparison Metrics

The single most important comparison in this experiment:

| Metric | 5-Symbol Universe | Expanded Universe (target) |
|--------|-------------------|---------------------------|
| **Sharpe** | -4.59 | **TBD** |
| **Cost drag (% of gross)** | 123.8% | **TBD** |
| **Directional accuracy (long on winners)** | 58.8% | **TBD** |
| **Directional accuracy (short on losers)** | 76.5% | **TBD** |
| **Net PnL** | -₹7,823 | **TBD** |
| **Rebalance events** | 17 | **TBD** |
| **Cost per rebalance** | ~₹254 | **TBD** |

The critical question: **Does cost drag fall significantly below 100% (ideally well below) when the universe expands to 50 symbols?** If cost drag remains above 100%, the conclusion is that universe size alone is insufficient and the remaining lever is data granularity.

---

*This protocol was written before any test-period evaluation results on the NIFTY 50 universe were computed. All parameter choices are locked from the 5-symbol experiment — nothing is being tuned on the larger universe.*
