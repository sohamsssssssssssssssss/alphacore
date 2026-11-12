# AlphaCore — K Expansion Experiment Report

**Date:** July 31, 2026 — 10:50 IST  
**Protocol:** `K_EXPANSION_EXPERIMENT_PROTOCOL.md` (pre-committed 2026-07-31 10:35 IST)  
**Experiment script:** `backend/experiments/k_expansion_experiment.py`  
**Raw results:** `k_expansion_results.json`  

**Direct predecessor:** `UNIVERSE_EXPANSION_EXPERIMENT_REPORT.md` — concluded the binding constraint was **K (position count), not N (universe size)**, and recommended exactly this test.

---

## ⚠️ HEADLINE LIMITATIONS — READ FIRST

1. **Still a 49-symbol universe** — not full NSE breadth. The short-leg results in particular may not generalize to a broader, more diverse pool.
2. **Daily-bar granularity unchanged** — daily OHLC bars with estimated bid/ask spreads (from daily High–Low range). No intraday or tick data; no slippage modeling beyond the spread/impact model.
3. **Equal-weight sizing may not reflect real capital constraints at higher K** — at K=10 each position is 1% of equity (~₹1,000 notional on ₹100k); real fractional/decimal lot sizing, minimum ticket costs, and per-symbol liquidity could differ materially. Also, no borrow-cost modeling for shorts (same as all prior experiments).

---

## 1. Pre-Committed Protocol and Locked Parameters

Everything except K was locked from the 49-symbol K=1 experiment; **no signal parameters were tuned**.

| Parameter | Value | Status |
|-----------|-------|--------|
| Signal | Cross-sectional relative strength (rank → long top-K, short bottom-K) | Locked |
| Lookback N | 20 trading days | Locked |
| Rebalance | Every 21 trading days (~monthly) | Locked |
| Universe | 49 NIFTY 50 symbols | Locked |
| Position sizing | **Equal weight: 10%/K of equity per position** (10% long + 10% short total deployed, **constant across K**) | This experiment's only convention change |
| Turnover | All positions closed and re-opened every rebalance (same as K=1) | Locked |
| Cost model | `CostModel()` default (k=0.0015, ₹20/trade, STT 0.1% on sells) | Locked |
| Train/test split | Chronological 70/30, split index 867 | Locked |
| Bootstrap | Stationary, 2,000 resamples, block length 21, seed 2026, 95% CI | Locked |
| **K values tested** | **1, 5, 10** (locked in protocol before any K>1 results) | This experiment |

**Step 0 confirmation:** The K=1 experiment sized each leg at 10% of equity (dollar-neutral). This generalizes to K>1 by splitting that 10% equally across K positions per leg — total capital deployed per rebalance is constant at 20% of equity regardless of K, isolating K's effect on cost drag. No other convention was used at any K.

**Step 1 confirmation:** Coverage was verified before running — the test period has 48–49 valid signal values on every single day, so 2K=20 is satisfied on every rebalance date for K=10. **Zero under-fill events occurred at any K** (confirmed again in-run).

---

## 2. Results — Full Comparison Table (All Configurations Tested So Far)

| Config | Sharpe | 95% CI | CI excl. 0 | Net PnL | Gross PnL | Cost drag | Trades (per rebal.) | Rebalances |
|--------|--------|--------|-----------|---------|-----------|-----------|--------------------|------------|
| 5-symbol, K=1 | -2.20 | [-3.59, -0.78] | YES (neg) | -₹7,890 | -₹3,562 | 121.5% | 68 (4) | 17 |
| 49-symbol, K=1 | -1.57 | [-3.14, +0.05] | NO | -₹7,474 | -₹3,177 | 135.3% | 68 (4) | 17 |
| **49-symbol, K=5** | **-3.24** | **[-4.44, -2.09]** | **YES (neg)** | **-₹11,948** | -₹2,238 | **433.9%** | 340 (20) | 17 |
| **49-symbol, K=10** | **-3.71** | **[-4.36, -3.06]** | **YES (neg)** | **-₹19,053** | -₹2,678 | **611.3%** | 680 (40) | 17 |

*The 49-symbol K=1 row in this run reproduces the universe-expansion run to the last rupee (Sharpe -1.5696, CI [-3.137, 0.048], net -₹7,474.37), confirming the K-generalized backtester is identical to its K=1 predecessor at K=1.*

### Per-position economics (why the numbers moved the way they did)

| K | Positions opened | Gross PnL / position | Cost / position | Net / position | Cost per rebalance | Gross per rebalance | CI width |
|---|-----------------|---------------------|-----------------|----------------|--------------------|--------------------|----------|
| 1 | 34 | -₹93.4 | ₹126.4 | -₹219.8 | ₹253 | -₹187 | 3.19 |
| 5 | 170 | -₹13.2 | ₹57.1 | -₹70.3 | ₹571 | -₹132 | 2.35 |
| 10 | 340 | -₹7.9 | ₹48.2 | -₹56.0 | ₹963 | -₹158 | 1.31 |

---

## 3. Sanity Checks (Step 4 of protocol)

| Check | Result |
|-------|--------|
| **Lookahead** | ✓ Passed — signal uses `pct_change(20)` (trailing returns only); ranking and selection at day *d* use only close data ≤ day *d*; entry at close of the rebalance day. No future information enters signal ranking or position selection. |
| **Degenerate / under-fill** | ✓ Passed — 0 rebalance dates with fewer than 2K valid signals at any K (min 48 of 49 valid daily). The target K was fully filled at every rebalance, so the cost-drag comparison is not distorted by under-filling. |
| **Cost consistency** | ✓ Passed — identical `CostModel()` default applied to every trade at every K. Cost per trade structure (impact + spread + ₹20 brokerage + STT) unchanged. |
| **Position-sizing consistency** | ✓ Passed — every open position at K=5 was 2.00% of equity, at K=10 was 1.00%; total deployed per rebalance = 10% long + 10% short at every K (20% of equity, constant). Total capital did not silently scale with K. |

---

## 4. Direct Test of the Prior Report's Diagnosis

The prior report claimed: *"with K=1, every rebalance executes a fixed 4 trades regardless of universe size... the binding constraint is K, not N... 5–10 positions per leg would aggregate more edge per cost cycle."*

**Verdict: the diagnosis is CONTRADICTED by the data — on both of its predictions.**

**(a) Cost drag did NOT decrease with K — it exploded:**

| K | Cost drag | Δ vs K=1 |
|---|-----------|----------|
| 1 | 135.3% | — |
| 5 | 433.9% | +298.6pp |
| 10 | 611.3% | +476.1pp |

The mechanism is unambiguous. Per-position costs fall with K (₹126 → ₹57 → ₹48) because positions get smaller — but per-rebalance costs rise linearly with K (₹253 → ₹571 → ₹963), driven by the fixed ₹20/trade brokerage × 4K trades per rebalance. Meanwhile **gross PnL per rebalance stayed flat** (-₹187 → -₹132 → -₹158): the aggregate edge per rebalance does NOT scale with K. Dividing the same gross PnL by the same total notional across more, smaller positions does not create edge — it just multiplies the cost events. Cost drag = costs/|gross| therefore tripled then quadrupled.

**(b) The Sharpe CI did tighten — but around an increasingly negative mean:**

| K | CI | Width |
|---|----|-------|
| 1 | [-3.14, +0.05] | 3.19 |
| 5 | [-4.44, -2.09] | 2.35 |
| 10 | [-4.36, -3.06] | 1.31 |

The averaging effect predicted by the report *did* occur mechanically — the CI narrowed by 59% from K=1 to K=10. But the center of the distribution moved **down**, not up (Sharpe -1.57 → -3.24 → -3.71), and at K≥5 the CI now cleanly excludes zero **in the wrong direction**: the strategy is now *statistically significantly negative* net of costs.

**Why the diagnosis failed:** the report assumed the signal's per-position edge (88.2% LONG directional accuracy at rank 1) extended to ranks 2–10. It does not. Gross PnL per position is negative at every rank bucket (each additional position adds ≈ -₹8 to -₹13 gross), and the short leg is negative at every K. Adding positions added cost without adding aggregate edge — the marginal edge per additional rank is zero or negative, not positive.

---

## 5. Bottom Line

> **Across all configurations tested so far — 5-symbol K=1, 49-symbol K=1, 49-symbol K=5, 49-symbol K=10 — is there ANY configuration that shows a cost-surviving, statistically significant edge?**

**NO.** No configuration shows a cost-surviving edge, and no configuration shows a statistically significant *positive* result. The 49-symbol K=1 result was the least-bad (Sharpe -1.57, CI [-3.14, +0.05] — the only configuration whose CI does not exclude zero, because it is borderline), but its point estimate is negative and its net PnL is -7.5%. Every other configuration is statistically significantly NEGATIVE (5-symbol K=1: CI entirely negative; 49-symbol K=5: CI [-4.44, -2.09]; 49-symbol K=10: CI [-4.36, -3.06]). K expansion did not turn the signal into a viable strategy — it converted a borderline-negative result into a definitively negative one. If the K=1 result should be "trusted" more than the others, it is only in the sense that it is the least-bad point estimate; it is not evidence of a real edge.

---

## 6. Closing Reflection — What to Try Next

With this experiment, both major structural levers have now been tested on the same signal, same data, same costs:

- **N (universe size):** 5 → 49 symbols — improved signal selection (LONG accuracy 58.8% → 88.2%) but left net PnL negative (universe expansion report).
- **K (position count):** 1 → 5 → 10 — left gross edge per rebalance flat while multiplying cost events, driving cost drag from 135% to 611% and Sharpe from -1.57 to -3.71 (this report).

Both tested levers failed to produce a cost-surviving edge on the same daily-bar dataset. The most informative remaining options:

**(a) Test higher K still (e.g., K=15–20).** The data shows no trend toward improvement: per-position gross PnL is negative at every rank, cost drag is rising superlinearly, and Sharpe is monotonically worse. The hypothesis "a higher K value will fix it" has now been falsified at two successive K steps; a third step is unlikely to be informative. Not recommended.

**(b) Accept that this signal/dataset/cost combination does not support a live strategy at retail trade sizes.** This is now the evidence-based default. Nine experiments across six mechanistically distinct signal families (momentum, mean-reversion, OFI, cross-sectional relative strength at two N and three K values, overnight gap, PEAD) have all failed to produce a cost-surviving edge on this data. The research value of AlphaCore's experiment program is the deliverable itself: a rigorous, well-documented set of honest negative results — including the single most important negative finding in this whole series: *the one signal that showed genuine directional skill (cross-sectional relative strength) has zero marginal edge beyond its top-ranked position on this daily data, and cannot cover per-trade costs at any position count tested.*

**(c) Paper-trading via a broker API as the next step.** This is the most informative *forward-looking* option if the goal is to keep exploring: backtests may be under- or over-stating real-world costs (slippage, partial fills, borrow costs, order-book depth) in ways further parameter search cannot resolve. A small, live paper-trading run of the 49-symbol K=1 variant would measure actual execution friction — the one unknown this entire backtest series has been forced to assume. If live costs are materially below the model's estimates, the K=1 variant's borderline CI (upper bound +0.05) is the only configuration worth the live test; if live costs match or exceed the model, the dataset's verdict is final.

---

## 7. Files Produced

- `K_EXPANSION_EXPERIMENT_PROTOCOL.md` — pre-committed protocol (2026-07-31 10:35 IST)
- `backend/experiments/k_expansion_experiment.py` — K-generalized backtester (verified to reproduce K=1 results exactly)
- `k_expansion_results.json` — raw results for all K values
- `K_EXPANSION_EXPERIMENT_REPORT.md` — this document
