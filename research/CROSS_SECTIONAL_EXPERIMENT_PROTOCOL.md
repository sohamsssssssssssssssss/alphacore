# Cross-Sectional Relative Strength Experiment — Protocol

**Date:** July 30, 2026 — 17:45 IST  
**Status:** **PRE-COMMITTED** — written before any test-period evaluation results were seen  
**Previous experiments:** 
- `SIGNAL_WEIGHT_EXPERIMENT_REPORT.md` (synthetic GBM: null/negative for momentum+MR+OFI)
- `REAL_DATA_EXPERIMENT_REPORT.md` (real NSE daily: null for NSGA-II vs equal weighting)
- `ALPHACORE_BACKTEST_REPORT.md` (single-symbol RELIANCE real backtest: Sharpe -11.3)

---

## Why This Protocol Exists

Three independent tests (single-symbol real backtest, synthetic GBM experiment, 5-symbol real-data experiment) all found that momentum + mean-reversion + OFI, in any weighting, does not produce a profitable strategy on daily NSE bars — Sharpe consistently negative, confidence intervals entirely below zero.

This experiment tests a **mechanistically different signal**: cross-sectional relative strength. Instead of asking "will this stock go up" (absolute direction), this asks "will this stock outperform the other stocks in the basket" (relative ranking). This can work even in a flat or declining market and has a different cost/edge structure because it's implemented as a long/short basket.

---

## 1. Signal Definition

### 1.1 Trailing Return (Signal)

For each symbol `s` on day `t`, compute the trailing N-day simple return:

```
ret_s(t) = (close_s(t) - close_s(t-N)) / close_s(t-N)
```

### 1.2 Lookback Window N — Selection Rule (Train Period Only)

Two candidate windows: **N=20** (one calendar month ≈ 20 trading days) and **N=60** (one quarter ≈ 60 trading days).

**Selection rule (pre-committed):** Compute the full backtest (long top K=1 / short bottom K=1, rebalance every 5 days, net of costs) on the **train period only** for both N=20 and N=60. Select the N that yields the **higher Sharpe ratio** on the train period. Lock this choice before touching test data.

N=20 and N=60 are chosen because:
- N=20: Standard 1-month momentum (Jegadeesh & Titman 1993 uses 3-12 months, but we have only ~5 years of data; 1-month is the shortest practically meaningful window)
- N=60: ~3-month momentum, more aligned with the classic literature (3-12 month horizons show strongest momentum effects in US equities)

### 1.3 Ranking Rule

Each day, rank the 5 symbols by trailing return `ret_s(t)` in descending order.

### 1.4 K — Number of Long/Short Legs

**K = 1.** Go long the single top-ranked symbol and short the single bottom-ranked symbol.

- With only 5 symbols, K=1 is the most concentrated, highest-conviction implementation of cross-sectional relative strength.
- K=2 (long top 2, short bottom 2) would be more diversified but would dilute the signal (bottom-2 and top-2 are closer in rank). K=1 gives the maximum spread in returns.
- Pre-committed: K=1.

### 1.5 Rebalance Frequency

**Every 5 trading days** (approximately weekly).

- Daily rebalancing would generate excessive turnover and cost drag — which dominated in every prior experiment. Every 5 days reduces turnover by 5× while still capturing the weekly signal.
- Rebalances occur on days 0, 5, 10, 15, ... of the test period (zero-indexed).

---

## 2. Strategy Mechanics

### 2.1 Position Sizing

Dollar-neutral equal-weight:

- **Long leg:** Invest `position_size_pct` of current equity in the top-ranked symbol (buy at ask price).
- **Short leg:** Short `position_size_pct` of current equity in the bottom-ranked symbol (sell short at bid price).
- **position_size_pct = 0.10** (10% of equity per leg, same as prior experiments for comparability).
- Total capital deployed per rebalance: 20% of equity (10% long + 10% short).

### 2.2 Position Management

- Between rebalances, positions are held regardless of daily rank changes (to avoid whip-saw turnover).
- At each rebalance day:
  1. **Close** existing long and short positions (sell long at bid, buy-to-cover short at ask).
  2. Compute costs on closing trades (both legs).
  3. **Open** new positions based on current ranking (buy new top-rank at ask, short new bottom-rank at bid).
  4. Compute costs on opening trades (both legs).
- If a stock is ranked in the middle 3 (not top or bottom), no position is taken in it.

### 2.3 Stop-Loss

No stop-loss on individual positions (the strategy is designed to hold between rebalances; adding a stop-loss would add cost drag and complicate the signal-to-execution mapping). This also matches the "hold periods" approach of prior experiments (just using rebalance-driven exits instead of signal-driven exits).

### 2.4 Initial Capital

₹100,000 (same as prior experiments for comparability).

---

## 3. Transaction Cost Model

Identical to all prior experiments — `CostModel()` default:

| Component | Value |
|-----------|-------|
| Market impact (k) | 0.0015 |
| Brokerage | ₹20.00 per trade |
| STT (Securities Transaction Tax) | 0.1% on sell trades only |
| Spread cost | Half the estimated bid-ask spread |

**Both legs** incur costs:
- Long entry: market impact + spread cost + brokerage
- Long exit (sell): market impact + spread cost + brokerage + STT
- Short entry (sell short): market impact + spread cost + brokerage + STT
- Short exit (buy-to-cover): market impact + spread cost + brokerage

**Short-selling cost assumption:** No separate stock-borrow cost is modeled. Real short-selling in Indian equities may involve borrow costs (typically 0.5–3% p.a. in the SLB market) and availability constraints. This is a **simplifying assumption** that understates costs. This limitation is stated explicitly in the report.

---

## 4. Data

| Property | Value |
|----------|-------|
| Source | Yahoo Finance via cached CSVs at `backend/data/real_nse_data/` |
| Symbols (5) | RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK (same basket as prior experiments) |
| Granularity | Daily OHLCV |
| Date range | 2021-07-30 to 2026-07-30 (1,239 rows per symbol) |
| Adjustments | `auto_adjust=True` (splits/dividends reflected in Close) |
| Corporate actions | Already applied via yfinance auto_adjust |

### Data Adaptation

- **Close price** → used to compute trailing returns and as reference price for bid/ask estimates.
- **Bid/Ask prices**: estimated as `close ± (spread_bps / 20000) × close` using the same daily High-Low range spread proxy as prior experiments.
- **Spread (bps)**: `((High − Low) / Close) × 10000`, clamped to [0.5, 50].
- **Limitation**: Daily bars only — no real bid/ask or depth data (same as all prior experiments).

---

## 5. Train/Test Split

Identical to prior experiments — chronological 70/30:

| Period | Start | End | Rows |
|--------|-------|-----|------|
| **TRAIN** | 2021-07-30 | 2025-01-29 | 867 |
| **TEST** | 2025-01-30 | 2026-07-30 | 372 |

The test period must discard the first N days (lookback window) because the trailing return cannot be computed. For N=20, this leaves 352 usable test days. For N=60, this leaves 312 usable test days.

The N selection (Step 1.2) is performed **only on the train set**, exactly as NSGA-II weight locking was done in prior experiments.

---

## 6. Primary Metric

**Sharpe ratio of the long/short basket's daily returns** (annualized, 252 periods/year, excess over 6.5% RFR).

For a market-neutral strategy:
- Sharpe is the standard metric (raw PnL depends on arbitrary scaling/leverage).
- A market-neutral strategy with Sharpe > 0 adds value regardless of market direction.
- The Sharpe of the *basket*, not individual legs, is the correct metric — the strategy is the combination, not either leg alone.

**Secondary metrics** (reported for context):
- Total net PnL (INR) of the basket
- Cost drag (% of gross PnL consumed by transaction costs)
- Number of rebalancing events and trades
- Win rate of individual legs
- Maximum drawdown of basket equity
- Per-leg breakdown (long leg vs short leg performance)

---

## 7. Confidence Interval

- **Method:** Stationary bootstrap (Politis-Romano) on daily basket returns
- **Mean block length:** 5 (daily returns with weekly rebalancing — 5 trading days is the natural block given rebalance schedule)
- **Resamples:** 2,000
- **Confidence:** 95%
- **Function:** `stationary_bootstrap_sharpe_ci()` from `backend/engines/backtest_metrics.py`

**Primary inference rule:** Does the 95% CI exclude zero? If yes, the Sharpe ratio is statistically distinguishable from zero at 95% confidence. If the CI upper bound is also negative, the strategy is *reliably unprofitable*.

---

## 8. Sanity Checks (Pre-Committed)

| Check | Pass Criteria |
|-------|---------------|
| **Lookahead** | Ranking at day T uses only returns up to day T. Verify code explicitly. |
| **Adequate trading** | Strategy must execute ≥ 10 rebalance events in test period. Fewer than 10 means result is unreliable. |
| **Rank dispersion** | Check whether rank ties occur in test period (unlikely with continuous prices, but if they do, document how ties are broken). |
| **Cost consistency** | Both legs use same `CostModel()` instance/parameters. |
| **Short-selling assumption** | State explicitly: no stock-borrow cost modeled. If result is positive, note that real short-selling costs would reduce net edge. |
| **Small-universe caveat** | N=5 symbols is a very small cross-section (typical deployments: 100-500+ names). State as headline limitation. |
| **Market regime** | Note the test period's overall market trend (e.g., was it a bull/bear market for these stocks?). |

---

## 9. Degenerate-Strategy Risks (Pre-Committed)

1. **Insufficient rank dispersion:** With only 5 large-cap stocks, trailing returns may be highly correlated, producing small rank differences. If the top and bottom returns are very close (e.g., < 10 bps apart), the signal is weak.
2. **Same symbol repeatedly at extremes:** A persistent top or bottom performer would cause the strategy to hold the same name for multiple rebalance periods, which is fine — it means the signal is consistent.
3. **Low trade count with N=60:** With 312 usable test days and rebalancing every 5 days, we expect ~62 rebalance events. Both N choices should yield adequate sample sizes.
4. **Cost dominance:** With 4 trades per rebalance (2 closes + 2 opens) and ~62 events, that's ~248 total trades in the test period. At ₹20/trade brokerage + market impact + STT, costs could dominate (as in prior experiments). Report cost drag prominently.

---

## 10. Reporting

Write `CROSS_SECTIONAL_EXPERIMENT_REPORT.md` with:
1. Headline limitations first: 5-symbol universe (small), daily bars (coarse), simplified short-selling cost assumptions.
2. The pre-committed protocol and locked parameters (including which N was selected and why).
3. Results: Sharpe, CI, sample size, cost drag, whether CI excludes zero.
4. All Step 8 sanity checks.
5. Reconciliation with prior findings (momentum/mean-reversion/OFI experiments).
6. Honest bottom-line conclusion.

---

## 11. What Would Invalidate This Run

- Choosing N, K, or rebalance frequency by peeking at test-period performance.
- Changing the N selection rule after seeing the train-period results.
- Post-hoc changing of the cost model parameters.
- Cherry-picking a different train/test split.
- Reporting only the better-performing leg (long or short) rather than the combined basket.

---

*This protocol was written before any test-period evaluation code was executed. All decisions are pre-committed.*
