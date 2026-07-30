# Real-Data Experiment Protocol — NSGA-II vs Equal Signal Weights

**Date:** July 30, 2026 — 15:20 IST  
**Status:** PRE-COMMITTED — written before any evaluation results were seen  
**Predecessor:** Synthetic experiment (`EXPERIMENT_PROTOCOL.md`, `SIGNAL_WEIGHT_EXPERIMENT_REPORT.md`)

---

## Question

Do NSGA-II-optimized signal weights (previously locked on the train period of real NSE daily data) beat naive equal weighting on **held-out real NSE daily data**, with bootstrap confidence intervals?

---

## Arms

### Arm A — NSGA-II-Tuned Weights
- Source: `locked_params.json` (weights selected on the train period of real RELIANCE daily data via the `run_real_backtest.py` pipeline)
- Weight vector: **[0.543, ~0, 0.457]** for [momentum, mean_reversion, OFI]
- Selection rule: "max Sharpe subject to Calmar > 1.0; else max Sharpe"
- **Frozen** — not re-optimized on the test period

### Arm B — Equal Weight Baseline
- Weight vector: **[1/3, 1/3, 1/3]** for [momentum, mean_reversion, OFI]
- Matches `_combined_signal()` in `backend/engines/backtester.py`

---

## Primary Metric

**Sharpe ratio** on the held-out test period (same as the synthetic experiment).

**Secondary metrics** (reported for context):
- Total net PnL (INR)
- Win rate, max drawdown, number of trades, cost drag
- Per-symbol breakdown

---

## Data

| Property | Value |
|----------|-------|
| Source | Yahoo Finance via `yfinance.download(..., auto_adjust=True)` |
| Symbols | RELIANCE.NS, TCS.NS, INFY.NS, HDFCBANK.NS, ICICIBANK.NS |
| Granularity | **Daily OHLCV** (minute data not reasonably available) |
| Date range | 2021-07-30 to 2026-07-30 (1,239 rows) |
| Corporate actions | `auto_adjust=True` — splits/dividends applied to OHLC |
| Missing data | None detected (all 5 symbols × all fields) |
| Cached at | `backend/data/real_nse_data/*.csv` |

### Data Adaptation to Snapshot Format

Following the same approach as `run_real_backtest.py` and the earlier honest backtest report:

- **Close price** → `mid_price`
- **Bid/Ask prices**: estimated as `mid ± (spread_bps / 20000) × mid`
- **Spread (bps)**: estimated from daily range: `((High − Low) / Close) × 10000`, clamped to [0.5, 50]
- **Bid/Ask volumes**: **50/50 split of daily volume** — no real bid/ask volume from daily data
- **Limitation stated explicitly**: OFI on daily data with 50/50 volume split is **always zero**. This was flagged as an anticipated degenerate-strategy risk in the earlier honest backtest and applies identically here.

---

## Train/Test Split

Chronological 70/30 split by date, matching the earlier honest backtest:

| Period | Start | End | Rows | % |
|--------|-------|-----|------|---|
| **TRAIN** | 2021-07-30 | 2025-01-29 | 867 | 70% |
| **TEST** | 2025-01-30 | 2026-07-30 | 372 | 30% |

The locked NSGA-II weights were originally selected on this exact train period (via `run_real_backtest.py`). Reusing them on the same train period is correct — the weights are frozen, not re-optimized.

---

## Procedure

1. Load cached OHLCV data for all 5 symbols
2. Convert each to the Snapshot format (with the bid/ask estimation above)
3. For each symbol:
   a. Run Arm A (NSGA-II weights) on test-period snapshots
   b. Run Arm B (equal weights) on the same test-period snapshots
   c. Record per-trade PnL, equity curve, and metrics
4. Aggregate across symbols:
   - Compute per-symbol Sharpe for each arm
   - Compute paired difference in equity at test-period end
   - Bootstrap CI across symbols (treating each symbol's trade sequence as a dependent block)

---

## Confidence Interval

- **Method**: Block bootstrap (stationary, geometric blocks) on per-trade returns
- **Mean block length**: 10 (matching `hold_periods`, the natural autocorrelation horizon)
- **Resamples**: 2,000
- **Confidence**: 95%
- Reuse `stationary_bootstrap_sharpe_ci()` from `backend/engines/backtest_metrics.py`

---

## Expected Degenerate-Strategy Risks (Pre-Committed)

1. **OFI = 0 on daily data**: With 50/50 bid/ask volume split, `_ofi_signal()` always returns 0. This means the 0.457 OFI weight in Arm A is effectively wasted, and the 0.333 OFI weight in Arm B is also wasted. The effective comparison is momentum-heavy (~54% momentum) vs. more balanced (~33% momentum + ~33% mean-reversion).
2. **Low trade count**: If either arm produces < 10 trades per symbol, flag it explicitly and report the metric as unreliable rather than presenting a false-precision number.
3. **Single-market-regime test period**: The 15-month test period may overlap a single market regime (bullish, bearish, or range-bound). Check and report.

---

## Inference Rule

- Primary: whether the **Sharpe CIs** of the two arms overlap at 95% confidence. If they don't overlap, the difference is statistically significant.
- Secondary: the **paired equity difference** at test-period end, with a bootstrap CI.
- If both metrics agree and the CI excludes zero in the direction favoring NSGA-II, the result is positive. If either metric shows no significant difference, the result is null. If the direction favors equal weights, report that plainly.

---

## Limitations (Pre-Committed)

1. **Daily data on minute-level signals**: The momentum/mean-reversion/OFI signals were designed for tick/minute-level data. The momentum windows (1, 5, 15 periods) span 1-15 trading days on daily data — a materially different regime. This was a limitation in the earlier honest backtest and remains so.
2. **Inferred bid/ask**: No real bid/ask depth. OFI is non-functional.
3. **Same split as prior tuning**: The exact same train/test split was used in the earlier `run_real_backtest.py` run that produced the locked weights. This means we're testing whether those specific weights hold up on the test period — which they already didn't (Sharpe -11.3). This experiment adds bootstrap CIs and multi-symbol validation.
4. **Single market regime in test**: The test period (2025-01 to 2026-07) should be checked for regime.
5. **No execution layer**: Same as the synthetic experiment — this tests signal quality, not execution quality.

---

*This protocol was written before any evaluation of the test period. All decisions were pre-committed.*
