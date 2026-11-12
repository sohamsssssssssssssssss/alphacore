# AlphaCore — Intraday (60-Minute Bar) Cross-Sectional Signal Experiment Report

**Date:** July 31, 2026 — 11:45 IST  
**Protocol:** `INTRADAY_SIGNAL_EXPERIMENT_PROTOCOL.md` (pre-committed 2026-07-31 11:20 IST)  
**Experiment script:** `backend/experiments/intraday_signal_experiment.py`  
**Raw results:** `intraday_signal_results.json`  
**Data:** `backend/data/nifty50_intraday_1h/` (yfinance 1.3.0, 60-minute bars, fetched 2026-07-31)  

---

## ⚠️ HEADLINE LIMITATIONS — READ FIRST

1. **Limited intraday history depth.** The only yfinance interval with adequate depth is **60-minute bars: 491 trading days (~2 years, 2024-08-01 → 2026-07-30)**. Finer intervals (1m: 7 days; 5m/15m/30m: ~44 days) were verified insufficient against the pre-declared minimum (≥60 days history with ≥30 days held out). The test period is 148 trading days — a real held-out window, but far shorter than the 371-day daily test period.
2. **49-symbol universe, no reductions.** All 49 symbols of the daily universe have full hourly coverage; the analysis grid (3,423 bars) is the intersection of all symbols' grids, which excludes 13 source-artifact bars (e.g., 2026-02-02 — a full trading day missing in 42 symbols; 2025-02-01 partial session; 2025-09-16 partial day) rather than filling them with manufactured prices.
3. **Minimal cadence adaptation, not a purpose-built intraday strategy.** The signal is the daily-bar cross-sectional relative-strength logic with a mechanical 1:1 bar-unit mapping (N: 20 days → 20 bars; rebalance: 21 days → 21 bars ≈ 3.2 trading days). This is a faster-decaying version of the same idea, not a new intraday design (no VWAP, order-flow, or microstructure features).
4. **Sharpe annualization convention.** The reported Sharpe uses the same 252/year convention as all prior experiments (for comparability). Proper hourly annualization (252×7 bars/year) scales the Sharpe and CI bounds by √7 ≈ 2.65 — the intraday result is even more negative (-8.2) under the correct convention. CI conclusion unaffected.

---

## Step 0 Outcome — Data Feasibility (30-minute time-box, completed)

| Interval | Verified depth (2026-07-31) | Meets ≥60-day bar? |
|----------|------------------------------|--------------------|
| 1m | 7 days | **NO** |
| 5m / 15m / 30m | ~44 trading days | **NO** |
| **60m / 1h** | **491–492 trading days** | **YES** |

- The earlier feasibility note (~18 months hourly) was **stale** — the current yfinance serves the full 730-calendar-day limit (~2 years) for hourly bars.
- Repo alternatives checked: `nse_fetcher.py`, `yfinance_feed.py` (1-day live lookback), `angel_feed.py` — **none provide historical intraday data**. No new paid source was integrated.
- Data quality: 49/49 symbols, 3,425–3,435 raw bars each, 100% timestamp alignment; 13 grid-artifact bars excluded via intersection (documented above).
- **STEP 0 CONCLUSION: PROCEED with 60-minute bars.**

---

## 1. Protocol and Locked Parameters

Mechanical daily→intraday adaptation; **nothing tuned on the intraday test period**:

| Parameter | Value | Status |
|-----------|-------|--------|
| Signal | Cross-sectional relative strength (rank trailing return → long top-1, short bottom-1) | Locked (same logic) |
| Lookback | **20 hourly bars** (~3.2 trading days) | 1:1 adaptation of 20 days |
| Rebalance | **Every 21 hourly bars** (~3.2 days) | 1:1 adaptation of 21 days |
| K | **1** (least-bad in K-expansion) | Locked |
| Universe | **49 NIFTY 50 symbols** | Locked, full coverage |
| Position sizing | 10% of equity per leg | Locked |
| Cost model | `CostModel()` default, **unchanged** | Per-execution model — verified below |
| Split | Chronological **70/30**: 2,396 train bars (2024-08-01 → 2025-12-19 15:15 IST) / 1,027 test bars (2025-12-19 → 2026-07-30, **148 trading days**) | Committed proportion |
| Bootstrap | Stationary, 2,000 resamples, **block length 21 bars** (matches the intraday rebalance cycle), seed 2026, 95% CI | Locked |

**Cost-model granularity check (plainly stated):** `CostModel()` is per-execution (impact + half-spread + ₹20 brokerage + STT-on-sell, charged once per trade) with **no per-day or per-frequency assumption** — it scales correctly to 48 rebalances × 4 trades over 148 days. The spread input is estimated from the same (High−Low)/Close formula with the same [0.5, 50] bps clip; verified hourly-bar ranges give comparable estimates to daily bars (mean 43.8 vs 49.8 bps; the 50 bps cap binds for ~half of bars at both granularities). **No cost-model adjustment required.**

---

## 2. Results

| Metric | Intraday 60m bars, K=1 |
|--------|-------------------------|
| **Sharpe** (252/yr convention) | **-3.10** |
| **95% CI** | **[-3.95, -2.35]** |
| CI excludes zero? | **YES — entirely negative** |
| Net PnL | **-₹19,235** (-19.2%) |
| Gross PnL | -₹7,834 |
| Total costs | ₹11,401 |
| **Cost drag** | **145.5%** |
| Rebalances | 48 |
| Trades | 192 (4.0 per rebalance) |
| Long / short leg (net) | -₹6,670 / -₹6,736 |
| Test period | 1,027 bars, 148 trading days (2025-12-19 → 2026-07-30) |

---

## 3. Sanity Checks (Step 4 of protocol)

| Check | Result |
|-------|--------|
| **Lookahead / timestamp alignment** | ✓ Passed — signal = `pct_change(20)` on trailing bars only; ranking, selection, and execution at bar *t* use only bars ≤ *t*. ✓ Passed — **0 missing bars** on the analysis grid; all 49 symbols share the identical 3,423-bar timestamp grid (the common intraday-data misalignment bug is excluded by construction and verified). |
| **Degenerate / under-fill** | ✓ Passed — 48 rebalances, 192 trades, exactly 4.0 trades per rebalance (expected at K=1); **0 under-fill events** (never fewer than 2 valid signals). |
| **Cost consistency** | ✓ Passed — identical `CostModel()` default, one cost event per execution, applied identically at intraday trade frequency; per-execution structure verified to need no frequency adjustment. |
| **Data quality** | ✓ Passed — 49/49 symbols; 3,423-bar intersection grid; 3 reduced-session days (2025-09-16, 2025-10-21, 2026-04-20) present identically in all symbols; 13 source-artifact bars excluded (2026-02-02 full-day gap in 42 symbols, 2025-02-01 special session, 2025-09-16 partial). |

---

## 4. Comparison with Daily-Bar Configurations (Context Only)

*Intraday test period (148 days) ≠ daily test period (371 days); Sharpe/CIs are comparable in construction, PnL magnitudes are not directly comparable.*

| Config | Sharpe | 95% CI | CI excl. 0 | Cost drag | Trades |
|--------|--------|--------|-----------|-----------|--------|
| Daily 49-sym, K=1 (best/least-bad) | -1.57 | [-3.14, +0.05] | NO | 135.3% | 68 |
| Daily 49-sym, K=5 | -3.24 | [-4.44, -2.09] | YES (neg) | 433.9% | 340 |
| Daily 49-sym, K=10 | -3.71 | [-4.36, -3.06] | YES (neg) | 611.3% | 680 |
| **Intraday 49-sym, K=1 (60m bars)** | **-3.10** | **[-3.95, -2.35]** | **YES (neg)** | **145.5%** | 192 |

---

## 5. Bottom Line

> **Does higher-frequency data allow this signal to clear transaction costs where daily bars couldn't?**

**NO — decisively.** The intraday version of the cross-sectional relative-strength signal is **statistically significantly negative net of costs** (Sharpe -3.10, CI [-3.95, -2.35] entirely below zero) and its cost drag (145.5%) remains above 100%. The faster-decaying version is *worse*, not better: at a ~3.2-day horizon the signal's gross edge does not exist — gross PnL is -₹7,834 (vs -₹3,177 for daily K=1 over a period 2.5× longer), and the higher rebalance frequency (48 vs 17 cycles) multiplies per-cycle costs (₹11,401 vs ₹4,297). The same pattern holds across every granularity tested: the signal's long/short ranking edge is too weak to cover realistic per-trade costs at any horizon, and shorter horizons make the cost problem strictly worse while the gross edge disappears.

---

## 6. Closing Reflection — A Complete, Honest Research Conclusion

All identified levers have now been tested on this data:

| Lever | Tested range | Outcome |
|-------|--------------|---------|
| Signal family | 6 families (momentum, mean-reversion, OFI, cross-sectional relative strength, overnight gap, PEAD) | No cost-surviving edge in any |
| Universe size (N) | 5 → 49 NIFTY 50 symbols | Signal quality improved; cost structure invariant; still net negative |
| Position count (K) | 1 → 5 → 10 | Marginal edge per rank ≈ 0; cost drag 135% → 611% |
| **Data granularity** | **Daily bars → 60-minute bars (this experiment)** | **Significantly negative net of costs; cost drag 145.5%** |

**No configuration across any lever shows a cost-surviving, statistically significant edge.** This is now a complete research conclusion, not a stopping point awaiting one more tweak. The two honest paths forward:

1. **Paper-trading validation via a broker API** — the only remaining unknown is whether the backtest cost model itself is miscalibrated (slippage, partial fills, real bid-ask on NSE). A small live paper run of the 49-symbol daily K=1 variant would measure actual execution friction. If live costs are materially lower than modeled, the daily K=1 result (CI upper bound +0.05) is the only configuration even plausibly worth a live test; if not, this dataset's verdict is final.
2. **Conclude the research phase and present AlphaCore's rigor as the deliverable** — TLA+-verified engineering, systematic experimental discipline (pre-committed protocols, locked parameters, bootstrap CIs, honest negative results), and a falsification-complete map of this signal/dataset/cost space is itself a strong research artifact: ten experiments, ten documented nulls, zero curve-fit claims.

Further backtesting on this data source is not recommended: three structural levers and six signal families have now been tested, and the last lever (granularity) failed in the same direction as all prior ones.

---

## 7. Files Produced

- `INTRADAY_SIGNAL_EXPERIMENT_PROTOCOL.md` — pre-committed protocol (2026-07-31 11:20 IST)
- `backend/data/nifty50_intraday_1h/` — 60-minute bar CSVs for 49 symbols (+ `metadata.json`)
- `backend/experiments/intraday_signal_experiment.py` — experiment script (reuses the K-expansion backtester unchanged; only the panel differs)
- `intraday_signal_results.json` — raw results
- `INTRADAY_SIGNAL_EXPERIMENT_REPORT.md` — this document
