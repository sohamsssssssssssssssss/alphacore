# Real-Data NSGA-II Signal Weight Experiment — Protocol

**Timestamp:** 2026-07-30T11:30:00Z  
**Author:** AlphaCore automated experiment pipeline  
**Status:** PRE-COMMITTED (before any evaluation run)

---

## 1. Question

Does NSGA-II-optimized signal-weight combination (momentum / mean-reversion / OFI) produce meaningfully better trading outcomes than naive equal weighting (1/3, 1/3, 1/3) on REAL historical NSE daily-bar data, net of realistic transaction costs?

---

## 2. Primary Metric

**Sharpe ratio** (annualized, excess over 6.5% risk-free rate, per-trade returns, 252 periods/year) — same metric used in the synthetic experiment and the prior honest RELIANCE backtest. Chosen because:

- It is the objective NSGA-II directly optimizes (via `-sharpe`)
- It is standard for strategy comparison across assets/horizons
- A confidence interval on the paired difference in Sharpe is interpretable

*Secondary metric (reported but not decisive):* Net PnL (after costs) over the test window.

---

## 3. Data

- **Source:** Yahoo Finance via `yfinance` (`auto_adjust=True`)
- **Symbols:** RELIANCE.NS, TCS.NS, INFY.NS, HDFCBANK.NS, ICICIBANK.NS (5 NSE large-caps)
- **Granularity:** Daily OHLCV (daily bars)
- **Period:** ~5 years (2021-07-29 to 2026-07-29, ≈1239 trading days per symbol)
- **Adjustments:** `auto_adjust=True` — splits and dividends are reflected in Close; no further corporate-action handling
- **OFI input estimation:** Bid/ask volume split 50/50 from daily Volume (same as prior RELIANCE backtest). This is an *approximation*, not real quote data. OFI signal will be degraded relative to its intended intraday use.
- **Spread estimation:** Daily High-Low range used as spread proxy, clamped to 0.5–50 bps.
- **Storage:** Raw DataFrames cached locally at `backend/data/real_nse_data/` for reproducibility.

---

## 4. Train / Test Split (Chronological — CRITICAL)

- **Split:** 70% train / 30% test by date (chronological, no random shuffle)
- **Split point:** Index `int(0.70 * N)` where N = number of trading days per symbol
- **Train window:** Earliest ~70% of dates (used for NSGA-II optimization)
- **Test window:** Most recent ~30% of dates (held out, never touched until final evaluation)
- **Exact dates** will be printed at runtime and recorded in the report.

---

## 5. Arms

### Arm A — NSGA-II-tuned (real-data-derived)
- NSGA-II run **fresh on the real train-period data** for each symbol independently
- Configuration: population=50, generations=30, seed=42 (fixed)
- Objectives: minimize `-Sharpe`, minimize `MaxDrawdown`
- Selection rule (pre-committed): *From the Pareto front, select the point maximizing Sharpe subject to Calmar > 1.0. If no point satisfies Calmar > 1.0, select max Sharpe.*
- The selected weight vector is **locked** and then evaluated once on the test period.

### Arm B — Equal-weight baseline
- Fixed weights: momentum=1/3, mean-reversion=1/3, OFI=1/3
- Same signal computation, same backtest engine, same cost model, same test data — only the weight vector differs.

---

## 6. Backtest Configuration (identical for both arms)

| Parameter | Value |
|-----------|-------|
| Hold periods | 10 days |
| Stop-loss | 0.5% (0.005) |
| Position size | 10% of current equity |
| Initial capital | ₹100,000 |
| Transaction costs | Market impact (k=0.0015), half-spread, ₹20/trade brokerage, 0.1% STT on sells |
| ADV lookup | Empty (falls back to default in CostModel) |

---

## 7. Evaluation & Statistics

1. **Per-symbol paired comparison:** Both arms run on the *identical* test-period snapshots for that symbol.
2. **Paired difference:** For each trade (or daily return if trade count is low), compute `Arm A − Arm B`.
3. **Bootstrap CI (primary):** 2,000 bootstrap resamples of the paired differences → 95% percentile CI for the mean paired difference.
   - If returns show autocorrelation (lag-1 ACF > 0.1), use block bootstrap with block length = 5 days (justified by typical mean-reversion horizon). State which was used.
4. **Per-arm Sharpe CI:** 2,000 bootstrap resamples of each arm's return series → 95% CI for Sharpe (each arm independently). Report whether CIs overlap.
5. **Sample size:** Report number of trades per arm per symbol. If any arm produces < 10 trades, flag as low-power and treat CI as unreliable.

---

## 8. Sanity Checks (must pass before reporting)

| Check | Pass Criteria |
|-------|---------------|
| Lookahead | No signal at T uses data from T+1 or later (verify adapter + signal functions) |
| Degenerate strategy | Both arms produce ≥ 10 trades on test period; if OFI-driven trades ≈ 0, flag explicitly |
| Cost consistency | Identical `CostModel` instance (or same parameters) used for both arms |
| Corporate actions | `auto_adjust=True` confirmed; no raw unadjusted prices used |
| Robustness | Report median paired difference alongside mean if distribution is heavy-tailed (|skew| > 1) |

---

## 9. Reporting

- **File:** `REAL_DATA_EXPERIMENT_REPORT.md`
- **Headline limitation first:** *"This experiment uses daily-bar OHLCV data with estimated bid/ask spreads and 50/50 volume splits for OFI. The signals were designed for intraday granularity; daily-bar adaptation is a material limitation. No real tick/quote data was used."*
- Results: paired-difference CI, Sharpe CIs, trade counts, all sanity-check outcomes
- Reconciliation with prior synthetic experiment (null result) and prior RELIANCE-only backtest (Sharpe -11.15)
- Decision-gate answer: Yes / No / Inconclusive — based strictly on whether CI excludes zero and effect is economically meaningful

---

## 10. What Would Invalidate This Run

- Re-running NSGA-II after seeing test results
- Changing the selection rule after seeing Pareto front
- Using a different train/test split than the one printed at runtime
- Cherry-picking symbols or metrics after seeing results
- Any modification to the cost model between arms

---

*End of Protocol. No evaluation code has been executed yet.*