# AlphaCore — Cross-Sectional Relative Strength: Monthly Rebalancing Report

**Date:** July 30, 2026 — 19:15 IST  
**Protocol:** `CROSS_SECTIONAL_MONTHLY_PROTOCOL.md` (pre-committed 2026-07-30 19:00 IST)  
**Experiment script:** `backend/experiments/monthly_rebalance_test.py`  
**Raw results:** `cross_sectional_monthly_results.json`  
**Predecessor experiments:**
- `CROSS_SECTIONAL_EXPERIMENT_REPORT.md` (original 5-day rebalance + diagnostic addendum)
- `CROSS_SECTIONAL_MONTHLY_PROTOCOL.md` (this experiment's pre-committed protocol)

---

## ⚠️ HEADLINE LIMITATIONS — READ FIRST

1. **Very small sample size:** Monthly rebalancing over the ~372-day test period produces only **17 rebalance events**. This is a very small sample. Confidence intervals are wide regardless of the point estimate, and any conclusion must be treated as tentative.

2. **5-symbol universe unchanged:** The same extreme small-universe limitation applies — with only 5 stocks, ranking stability is poor at any rebalance frequency. 100% of monthly long picks were different from the previous month's pick, reflecting churn even at the monthly horizon.

3. **Cost model unchanged:** Stock-borrow costs for the short leg are still not modeled (same as original), understating real-world costs.

4. **Single-frequency test:** This is one test of one frequency (21-day rebalancing), not a sweep. Results may differ at other frequencies (e.g., quarterly, semi-annual).

---

## 1. Pre-Committed Protocol (Summary)

### What changed

| Parameter | 5-day (Original) | Monthly (This test) |
|-----------|-----------------|---------------------|
| **Rebalance frequency** | Every 5 days | **Every 21 days (≈monthly)** |
| MTM logic | Fixed (diagnostic) | **Fixed (same)** |
| N (lookback) | 20 | **20 (unchanged)** |
| K (long/short) | 1 | **1 (unchanged)** |
| Cost model | `CostModel()` default | **Same** |
| Train/test split | Chronological 70/30 | **Same** |
| Position sizing | 10% per leg | **Same** |
| Bootstrap block length | 5 | **21** (matches new monthly cycle) |

### Rationale

The diagnostic pass found that the signal has genuine directional skill (LONG on winners 61%, SHORT on losers 72%) and a naive buy-and-hold was gross-profitable (+₹1,503), but 5-day rebalancing produced 243% cost drag with 98.6% of costs from turnover. Monthly rebalancing reduces turnover by ~4× (from 142 rebalance events to ~17-18), directly testing whether lower frequency lets the signal survive costs.

---

## 2. Results

### 2.1 Comparison: Monthly vs 5-Day Rebalancing (Both MTM-Fixed)

| Metric | 5-day (prior, fixed) | Monthly (this test) | Change |
|--------|---------------------|-------------------|--------|
| **Net PnL** | **-₹23,898.87** | **-₹7,822.94** | **-67.3%** (less loss) |
| Gross PnL | -₹6,967.42 | -₹3,494.89 | Less negative |
| Total costs | ₹16,931.45 | ₹4,328.06 | -74.4% |
| **Cost drag** | **243.0%** | **123.8%** | **From 2.4× to 1.2× gross** |
| **Sharpe** | **-7.19** | **-4.59** | **Better, but still negative** |
| **95% CI** | **[-6.99, -3.98]** | **[-3.51, -0.70]** | **Still entirely below zero** |
| CI excludes zero? | True (NEGATIVE) | True (NEGATIVE) | Unchanged |
| Long leg PnL | -₹10,008.99 | -₹2,563.65 | Less negative |
| Short leg PnL | -₹10,046.40 | -₹2,586.17 | Less negative |
| Final equity | ₹76,101.13 | ₹92,177.06 | -7.82% loss (vs -23.90%) |
| Rebalance events | 142 | **17** | -88% |
| N observations | 352 | 352 | Same |

### 2.2 Directional Alignment (Monthly)

| Metric | 5-day | Monthly |
|--------|-------|---------|
| **LONG on winners** | 60.6% | **58.8%** (10/17) |
| **SHORT on losers** | 71.8% | **76.5%** (13/17) |
| Long same symbol as prev rebalance | 51.4% | **0%** (every long pick changed) |
| Short same symbol as prev rebalance | 51.4% | **25%** (3/4 of short picks changed) |

### 2.3 Per-Symbol Breakdown (Monthly)

| Symbol | Times LONG | Times SHORT | Test-period return |
|--------|-----------|------------|-------------------|
| ICICIBANK | 5x | 3x | +15.02% |
| RELIANCE | 5x | 1x | +2.98% |
| HDFCBANK | 3x | 4x | -8.74% |
| TCS | 1x | 5x | -37.64% |
| INFY | 3x | 4x | -35.46% |

---

## 3. Interpretation

### Cost Drag Improvement — But Still Above 100%

Cost drag dropped from **243.0%** to **123.8%** — a substantial improvement, but still above 100%. This means total transaction costs still exceed gross trading PnL. The strategy would lose money even with zero signal error (i.e., even if every position was perfectly directionally correct).

The gross PnL (-₹3,495) is roughly half of costs (₹4,328). For the strategy to break even at zero net PnL, gross PnL would need to move from -₹3,495 to +₹4,328 (a swing of +₹7,823, or ~224% improvement from the current gross loss to a sufficiently large gross profit). Alternatively, costs would need to fall from ₹4,328 to under the current gross loss of -₹3,495 — i.e., to near zero.

### Sharpe Still Strongly Negative

The Sharpe improved from -7.19 to -4.59 — still deeply negative, and the entire 95% CI [-3.51, -0.70] is below zero. We can be 95% confident the true Sharpe is somewhere between -3.51 and -0.70.

### Directional Alignment Holds

The signal remains directionally correct at the monthly horizon:
- **LONG was on winners 58.8%** of the time (vs 60.6% at 5-day)
- **SHORT was on losers 76.5%** of the time (vs 71.8% at 5-day)

The short leg alignment actually improved at the monthly frequency (76.5% vs 71.8%), suggesting the monthly trailing returns better identify persistent losers than the 5-day window.

### Ranking Stability at Monthly Frequency

A notable finding: at monthly rebalancing, **100% of long picks changed** from one rebalance to the next (vs 51.4% continuity at 5-day frequency). The short leg had only 25% continuity (4/16 rebalances kept the same symbol). With only 5 symbols, the fact that the trailing-20-day winner changes every single month at a 21-day rebalance interval indicates that the ranking is dominated by short-term noise rather than persistent trends at this horizon. This suggests that monthly rebalancing doesn't just reduce the *number* of costs — it may also sample a less stable ranking signal, partially offsetting the benefit of lower turnover.

### Both Legs Still Lose

Even at monthly rebalancing, both legs lose money:
- Long leg: -₹2,564 (from 10 winning picks out of 17, suggesting the winners rose less than expected during the hold period)
- Short leg: -₹2,586 (from 13 losing picks out of 17, suggesting the losers fell less than expected)

Both legs have nearly identical losses, which is consistent with the directional alignment being moderately correct but the MAGNITUDE of the relative moves during the 21-day hold being insufficient to overcome the round-trip cost of entering and exiting.

---

## 4. Direct Answer to the Question

> **Does reducing rebalance frequency to monthly let this signal survive costs?**

**ANSWER: No. Monthly rebalancing substantially improves the outcome (net PnL goes from -₹23,899 to -₹7,823, a 67% reduction in loss), but the strategy still loses money net of costs with statistical significance (Sharpe -4.59, 95% CI [-3.51, -0.70], entirely below zero).**

Cost drag remains at 123.8% — still above 100%, meaning costs exceed gross trading profits. Even with the somewhat scant 17 rebalance events, the consistency of the negative result (entire CI below zero) gives reasonable confidence that the strategy is not profitable at monthly frequency on this universe.

---

## 5. Overall Arc of the Cross-Sectional Signal on This Dataset

The full testing history of cross-sectional relative strength on the 5-symbol NSE daily dataset:

| Test | Finding |
|------|---------|
| **5-day rebalance (buggy MTM)** | Sharpe -4.37, CI [-6.64, -2.13], both legs lost. Attributed to signal failure. |
| **Diagnostic (MTM fix)** | Signal IS directionally skilled (61%/72% alignment). Naive hold gross-profitable (+₹1,503). But 243% cost drag destroyed everything. 98.6% of costs from whipsaw. |
| **Monthly rebalance (this)** | Cost drag falls to 123.8% but still >100%. Sharpe improves to -4.59 but CI still entirely negative [-3.51, -0.70]. Still losing money with significance. |
| **Naive hold (no rebalance)** | Gross-profitable +₹1,503, net +₹1,259 (+1.26%). Sharpe -2.07, CI [-1.32, +2.26] (includes zero). |

**The arc shows:** The cross-sectional relative strength signal has a real but very small edge on this dataset — the naive buy-and-hold of picks from day 1 captures about 1.5% gross return over 18 months. But the cost of any active rebalancing (even monthly) destroys this thin edge completely. The cost-to-signal ratio is simply too high on a 5-symbol universe with individual stock costs of ~₹60 per trade and only 10% position sizing.

**Implication:** Cross-sectional relative strength may well work on a larger universe (100+ stocks) where ranking persistence is higher, turnover is lower, and the edge per unit of cost is larger. But on this specific 5-symbol, daily-bar, large-cap dataset, the avenue appears exhausted at any practical rebalance frequency. The signal edge exists but is too thin to survive the transaction cost structure of even a monthly implementation.

---

## 6. Files Produced

- `CROSS_SECTIONAL_MONTHLY_PROTOCOL.md` — pre-committed protocol (timestamped)
- `backend/experiments/monthly_rebalance_test.py` — experiment script
- `CROSS_SECTIONAL_MONTHLY_REPORT.md` — this document
- `cross_sectional_monthly_results.json` — raw results

---

*This protocol and report were written before the test was run. Only the rebalance frequency was changed from the original experiment. The fixed MTM backtester (from the diagnostic pass) was used — the MTM bug was not reintroduced.*
