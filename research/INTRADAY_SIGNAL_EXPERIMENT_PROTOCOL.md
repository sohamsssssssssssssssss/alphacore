# Intraday Signal Experiment — Cross-Sectional Relative Strength on 60-Minute Bars

**Date:** July 31, 2026 — 11:20 IST  
**Status:** **PRE-COMMITTED** — written before any intraday test-period evaluation results were computed  
**Experiment script (to be written):** `backend/experiments/intraday_signal_experiment.py`  
**Data:** `backend/data/nifty50_intraday_1h/` (fetched 2026-07-31)  

**Predecessor results (all daily-bar, all no cost-surviving edge):**
1. Single-symbol momentum/mean-reversion/OFI: Sharpe -11.3
2. NSGA-II weight optimization: null
3. Cross-sectional 5-day rebalance, 5-symbol: cost drag 243%
4. Cross-sectional monthly, 5-symbol: cost drag 123.8%, Sharpe -4.59
5. Overnight gap reversal: Sharpe -6.80
6. PEAD: net -₹4,622
7. Universe expansion (49-symbol, K=1, monthly): Sharpe -1.57, CI [-3.14, +0.05], cost drag 135.3%
8. K expansion (49-symbol, K=1/5/10): K=1 least-bad; cost drag 135% → 611% as K↑; no edge

---

## STEP 0 OUTCOME — Data Feasibility (time-boxed, completed)

### 1. Verified intraday depth (yfinance 1.3.0, installed, tested live 2026-07-31)

| Interval | Actual depth | ≥ 60 trading days? |
|----------|--------------|--------------------|
| 1m | 7 days | **NO** |
| 5m / 15m / 30m | ~44 trading days | **NO** |
| **60m / 1h** | **491–492 trading days (~2 years)** | **YES** |

The 60-minute interval is the ONLY interval with adequate depth (this differs from the earlier feasibility note, which reported ~18 months for hourly — the actual current limit is the full 730 calendar days, ~2 years).

### 2. Minimum viable window (set BEFORE checking)

**Pre-declared bar: ≥ 60 trading days of history, enabling a held-out test period of ≥ 30 trading days after a ≥ 30-day train/warmup window.** The available hourly history provides ~492 trading days; the held-out test period below is 147 trading days — comfortably above the bar.

### 3. Alternative data sources (checked)

`nse_fetcher.py` (live orderbook), `yfinance_feed.py` (live feed, 1-day lookback), `angel_feed.py` (live) — **none provide historical intraday data**. No new paid data source was integrated (explicitly out of scope). yfinance hourly was sufficient.

### 4. Data quality (verified before protocol finalization)

- **49/49 symbols** of the daily universe have full hourly coverage (TATAMOTORS failed — as in the daily fetch, excluded from both universes).
- 3,425–3,435 bars per symbol; **100% timestamp alignment** across symbols (<0.3% missing bars for the worst symbol, 0 extras).
- Timestamp grid: 09:15, 10:15, …, 15:15 IST labels (7 bars/day: 6 full hours + final 15-minute partial bar); 2 short days (2025-10-21: 2 bars, 2026-04-20: 3 bars — reduced sessions) present identically in all symbols.

**STEP 0 CONCLUSION: PROCEED with 60-minute bars.**

---

## Part A — Intraday Signal Definition (minimal daily→intraday adaptation)

Everything is a direct 1:1 bar-for-bar mapping of the locked daily-bar configuration; **no signal parameters are tuned** beyond the mechanical bar-unit substitution:

| Parameter | Daily (locked) | Intraday (this experiment) | Rationale |
|-----------|----------------|----------------------------|-----------|
| Signal | Cross-sectional relative strength | **Identical logic** (rank trailing returns → long top-1, short bottom-1) | Same signal family |
| Lookback N | 20 days | **20 bars** (~3.2 trading days) | Direct N-bars substitution — a faster-decaying version of the same idea |
| Rebalance | Every 21 days | **Every 21 bars** (~3.2 trading days) | Direct 1:1 cadence mapping |
| K | 1 (least-bad in K-expansion) | **1** | Locked — K search is not re-opened |
| Universe | 49 NIFTY 50 symbols | **Same 49 symbols** | Full intraday coverage verified |
| Position sizing | 10% of equity per leg | **10% of equity per leg** | Identical |
| Cost model | `CostModel()` default | **`CostModel()` default, unchanged** | Per-execution model — see check below |
| Initial capital | ₹100,000 | **₹100,000** | Identical |

### Cost-model granularity check (Step 1.4 of task)

The `CostModel()` is a **per-execution** model (impact + half-spread + ₹20 brokerage + STT-on-sell, charged once per trade). It contains **no per-day or per-period assumption** — with ~49 rebalances × 4 trades in the test period (vs 17 × 4 daily), each execution pays the same per-trade costs, so the model scales correctly to higher trade frequency. The one input that changes with granularity is the **spread estimate**, derived from the bar's (High−Low)/Close range (same formula, same [0.5, 50] bps clip as daily). Verified: hourly-bar ranges give mean 43.8 bps vs daily 49.8 bps — the clip cap (50 bps) binds for ~half the bars at both granularities, so the spread input is comparable, not understated. **No cost-model adjustment is required.**

### Train/test split (chronological, same 70/30 discipline)

| Period | Range | Bars | Trading days |
|--------|-------|------|--------------|
| TRAIN | 2024-08-01 09:15 → 2025-12-19 15:15 IST | 2,398 | ~343 |
| TEST | 2025-12-19 → 2026-07-30 15:15 IST | **1,029** | **~147** |

Split index: **2,398 of 3,427 bars** (70/30). Test period is 147 trading days — well above the 30-day minimum.

---

## Part B — Metrics

1. **Primary: Sharpe ratio** (annualized, 252/year, excess over 6.5% RFR) of the basket's **per-bar returns, net of all costs**, over the held-out intraday test period — same `compute_sharpe` as every prior experiment.
2. **Secondary: cost drag (%)** = total costs / |gross PnL| — comparable in spirit to the daily-bar numbers (same definition), noting the underlying trade frequency differs.
3. **Bootstrap CI:** stationary bootstrap (Politis-Romano), **2,000 resamples, seed 2026, 95% CI, block length = 21 bars** — chosen to match the intraday rebalance cycle (the autocorrelation horizon of interest), same principle as the daily experiments' block length of 21 days.
4. Reported per run: Sharpe, CI, CI-excludes-zero, net PnL, gross PnL, total costs, cost drag %, rebalance count, total trades, trades per rebalance.

---

## Part C — Sanity Checks

1. **Lookahead**: trailing-return signal uses only bars ≤ current bar; trade executes at the current bar's close (same convention as daily); no future bar enters any decision. **Timestamp alignment**: every symbol must share ≥99% of the reference bar grid (verified in Step 0; re-verified in-run).
2. **Degenerate / under-fill**: flag any rebalance bar with < 2 valid signals (under-filled K=1) or abnormal trade counts.
3. **Cost consistency**: identical `CostModel()` instance, one cost event per execution, no per-K or per-frequency adjustments.
4. **Data quality**: report bars-per-symbol, missing bars vs the reference grid, and the 2 short trading days (2025-10-21, 2026-04-20).

---

## Part D — What Would Invalidate This Run

- Re-tuning N, K, cadence, sizing, or the cost model for intraday data.
- Changing the universe based on intraday test-period performance.
- Changing the split or bootstrap settings after seeing results.
- Reporting only favorable sub-periods or alternative lookbacks.
- Silently reusing the daily cost model without the granularity check above (done — no adjustment needed, stated here).

---

*This protocol was written before any intraday test-period results were computed. The intraday adaptation (N=20 bars, rebalance every 21 bars, K=1) is a mechanical 1:1 bar-unit mapping of the locked daily configuration — nothing is tuned on the intraday test period.*
