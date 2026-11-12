# K Expansion Experiment — Cross-Sectional Relative Strength on NIFTY 50

**Date:** July 31, 2026 — 10:35 IST  
**Status:** **PRE-COMMITTED** — written before any K>1 test-period evaluation results were computed  
**Experiment script (to be written):** `backend/experiments/k_expansion_experiment.py`  
**Predecessor experiments:**
1. Single-symbol momentum/mean-reversion/OFI (Sharpe -11.3)
2. NSGA-II weight optimization, synthetic + real (null)
3. Cross-sectional relative strength, 5-day rebalance, 5-symbol (cost drag 243%, Sharpe -7.19)
4. Cross-sectional relative strength, monthly rebalance, 5-symbol (cost drag 123.8%, Sharpe -4.59)
5. Overnight gap reversal (Sharpe -6.80)
6. PEAD (net -₹4,622)
7. **Universe expansion 5 → 49 symbols, K=1, monthly (cost drag 135.3%, Sharpe -1.57, CI [-3.14, 0.05])** — the direct predecessor of this experiment.

---

## Why This Task Exists

The universe expansion report concluded that with K=1, every rebalance executes a fixed 4 trades regardless of universe size (N). Expanding N to 49 symbols improved the signal's directional quality (LONG winners 58.8% → 88.2%) but could not convert that better signal into more positions — the binding constraint identified was **K (position count), not N (universe size)**. This experiment tests that diagnosis directly: the SAME locked cross-sectional signal, the SAME 49-symbol universe, the SAME rebalance schedule — varying ONLY K.

---

## STEP 0 OUTCOME — Position-Sizing Convention (Confirmed from K=1 Experiment)

- The K=1 experiment (`universe_expansion_experiment.py`) used **`POSITION_SIZE_PCT = 0.10` — 10% of equity per leg, dollar-neutral**: one long position and one short position, each sized at 10% of equity (20% of equity gross deployed per rebalance).
- **Generalization to K>1: equal weight across the K longs and K shorts.** Each of the K long positions is sized at `0.10/K` of equity, each of the K short positions at `0.10/K` of equity. Total capital deployed per rebalance is therefore **constant at 20% of equity (10% long + 10% short) regardless of K**.
- This is the correct convention for isolating K's effect on cost drag: as K increases, the same total notional is sliced into more, smaller positions. Per-rebalance trading costs scale with 4K trades (close K longs + close K shorts + open K longs + open K shorts) — the direct structural test of whether more, smaller positions aggregate more edge per cost cycle.
- No other sizing convention is used at any K; sizing never silently scales total deployment with K.

---

## Part A — K Values Tested

### 1. Locked K List (chosen before any K>1 results were seen)

| K | Longs | Shorts | Trades per rebalance | Rationale |
|---|-------|--------|---------------------|-----------|
| **1** | 1 | 1 | 4 | Baseline — prior result exists (49-symbol, cost drag 135.3%) |
| **5** | 5 | 5 | 20 | Meaningful diversification step-up |
| **10** | 10 | 10 | 40 | Max sensible for this universe — requires ≥20 valid symbols per rebalance |

No other K values are tested. **The K list is locked now, before any K>1 runs.**

### 2. Coverage Confirmation (checked BEFORE running)

Checked the panel directly: the 49-symbol test period has **48–49 valid signal values on every single day** (min=48, median=49 of 49). Therefore 2K=20 is satisfied on every rebalance date for K=10 throughout the test period — **zero under-fill events possible**. (Re-verified in the experiment run's sanity checks.)

### 3. Locked Strategy Parameters (identical to the 49-symbol K=1 experiment — NOTHING else varies)

| Parameter | Value | Locked by |
|-----------|-------|-----------|
| Signal | Cross-sectional relative strength: trailing N-day return → rank → long top-K, short bottom-K | 5-symbol experiment |
| Lookback N | **20** trading days | 5-symbol experiment |
| Rebalance | **Every 21 trading days** (~monthly) | 5-symbol experiment |
| Position sizing | **10%/K of equity per position** (equal weight; 10% long + 10% short total) | This protocol (Step 0) |
| Cost model | **`CostModel()` default** (k=0.0015, ₹20/trade, STT 0.1% on sells) — unchanged | All prior experiments |
| Initial capital | ₹100,000 | All prior experiments |
| Universe | **49 NIFTY 50 symbols** (`backend/data/nifty50_data/`) — unchanged | Universe expansion experiment |
| Train/test split | Chronological 70/30, **split index 867** — unchanged | All prior experiments |
| Turnover convention | All K positions closed and re-opened at every rebalance (same as K=1: no "keep if still ranked" optimization) | Matches K=1 mechanics |

**Explicit statement: NO signal parameters are being tuned. Only K varies. Universe, lookback, rebalance frequency, and cost model are unchanged.**

---

## Part B — Metrics

### 1. Primary Metric (per K)

**Sharpe ratio** of the long/short basket's daily returns (annualized, 252/year, excess over 6.5% RFR), **net of all transaction costs**, over the held-out test period — computed with the same `compute_sharpe` function as every prior experiment.

### 2. Secondary Metric (per K) — the direct test of the prior diagnosis

**Cost drag = total transaction costs / |gross PnL|** (%). The prior report's diagnosis predicts: holding N and the signal fixed, **increasing K should lower cost drag as a percentage of gross PnL** — because more independent bets per rebalance aggregate more edge per cost cycle.

### 3. Confidence Intervals

- Method: **stationary bootstrap (Politis-Romano)** on daily basket returns — identical to prior experiments
- Mean block length: **21** (matches monthly rebalance cycle)
- Resamples: **2,000**; Seed: **2026**; 95% CI

### 4. Reported Per-K Statistics

Sharpe, 95% CI, CI-excludes-zero flag, net PnL, gross PnL, total costs, cost drag (%), trades per rebalance (4K), total trades over test period, rebalance count, long/short leg PnL.

### 5. Comparison Table

Single table across all configurations tested so far: **5-symbol K=1, 49-symbol K=1, 49-symbol K=5, 49-symbol K=10** — Sharpe, CI, cost drag, net PnL, trades.

---

## Part C — Sanity Checks (same discipline as every prior experiment)

1. **Lookahead**: signal uses only trailing returns (`pct_change(20)`); entry at close uses only data available at that time; ranking computed from same-day trailing returns only.
2. **Degenerate-strategy / under-fill**: flag any rebalance date with fewer than 2K valid signal values (strategy would under-fill its target K, distorting the cost-drag comparison). Report count per K.
3. **Cost consistency**: identical `CostModel()` applied to every trade at every K — no per-K cost assumption changes.
4. **Sizing consistency**: verify each position's notional = `0.10/K × equity` at open for every K, so total deployed per rebalance is comparable across K (20% of equity).

---

## Part D — What Would Invalidate This Run

- Changing any signal parameter, the universe, or the cost model between K runs.
- Choosing K values after peeking at their test performance.
- Changing the sizing convention between K values (e.g., per-position notional fixed at 10% at every K — this would confound the cost-drag comparison by scaling total deployment with K).
- Changing the train/test split or bootstrap settings.
- Reporting only the best-performing K.

---

*This protocol was written before any K>1 test-period results were computed. The K list (1, 5, 10) is locked. Nothing is being tuned on the test period.*
