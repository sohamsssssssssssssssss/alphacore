# AlphaCore — Real Market Data Backtest Report
**Date:** 2026-07-29
**Author:** Automated audit pipeline (run_real_backtest.py)

---

## Bottom Line

**Sharpe: -11.3, Calmar: -1.0, on real NSE data, with locked parameters, single test run.**

The strategy lost money consistently on held-out data. All four sub-strategies (momentum, mean-reversion, OFI, combined) produced negative Sharpe ratios. This is the honest result of running the existing AlphaCore backtesting infrastructure on real daily NSE data — it does not generate alpha in this configuration.

---

## 1. Data Source

| Property | Value |
|---|---|
| Provider | Yahoo Finance (via yfinance, auto_adjust=True) |
| Symbol | RELIANCE.NS (Reliance Industries, NSE) |
| Frequency | Daily OHLCV |
| Total rows | 1,239 |
| Date range | 2021-07-29 to 2026-07-29 |

### Data Preparation
- **Close price** used as `mid_price` in Snapshot format
- **Bid/Ask prices** estimated as `mid ± (spread_bps/20000) * mid`
- **Spread (bps)** estimated as `((High - Low) / Close) * 10000`, clamped to 0.5–50 bps
- **Bid/Ask volumes** split 50/50 of daily volume (no real bid/ask volume available from daily data)
- 0 missing Close values across all 5 NSE symbols pulled

**Cached data:** None found in repo. Live pull from Yahoo Finance was used.

### Symbols Available (all pulled, only RELIANCE used for backtest)
RELIANCE.NS, TCS.NS, INFY.NS, HDFCBANK.NS, ICICIBANK.NS

---

## 2. Train/Test Split

| Period | Start | End | Rows | % |
|---|---|---|---|---|
| **TRAIN** | 2021-07-29 | 2025-01-29 | 867 | 70% |
| **TEST** | 2025-01-30 | 2026-07-29 | 372 | 30% |

**Split method:** Chronological 70/30 by row index at `int(1239 * 0.70) = 867`.

**Test period regime:** Mean daily return 0.0157% (4.05% annualized). Period is mildly bullish but within normal range. **Not** flagged as a single-extreme-regime window.

---

## 3. Tuning Method: NSGA-II

### Pre-Committed Selection Rule
Before seeing any test data, the rule was locked:
> **"From the NSGA-II Pareto front, select the point that maximizes Sharpe ratio subject to Calmar > 1.0 (positive risk-adjusted return). If no point satisfies Calmar > 1.0, select the max Sharpe point."**

### NSGA-II Configuration
- **Population:** 50
- **Generations:** 30
- **Objectives:** minimize(-Sharpe), minimize(MaxDrawdown)
- **Signal weights optimized:** momentum, mean_reversion, ofi
- **Returns matrix shape:** (3, 10) — 10 trade observations × 3 signals

### Train-Period Strategy Performance
Even on training data, all strategies were deeply negative:

| Strategy | Sharpe | Calmar | Trades | Win Rate | Cost Drag |
|---|---|---|---|---|---|
| Momentum | -7.00 | -0.91 | 161 | 23.6% | 192.7% |
| Mean Reversion | -10.27 | -0.98 | 118 | 13.6% | 78.8% |
| OFI | 0.00 | 0.00 | 0 | 0.0% | N/A |
| Combined (equal) | -7.32 | -0.92 | 164 | 22.0% | 171.9% |

**OFI produced 0 trades** on daily data because bid/ask volumes are symmetrical (50/50 split), making Order Flow Imbalance always zero.

### NSGA-II Pareto Front
The optimizer found a front of 26 points, all with high Sharpe (~8.57) and tiny drawdowns. This is **spurious** — the returns matrix had only 10 observations per signal, so the optimizer was fitting to noise. The weights effectively split between momentum (~54%) and OFI (~46%), with mean-reversion at ~0%.

### Locked Parameters (timestamp: 2026-07-29T20:32:58)

```json
{
  "weights": [0.5426, 0.0000, 0.4574],
  "weight_labels": ["weight_momentum", "weight_mean_reversion", "weight_ofi"],
  "selection_rule": "max Sharpe subject to Calmar > 1.0; else max Sharpe",
  "timestamp": "2026-07-29T20:32:58.655893",
  "train_config": {
    "symbol": "RELIANCE",
    "hold_periods": 10,
    "stop_loss_pct": 0.005,
    "position_size_pct": 0.1,
    "initial_capital": 100000.0
  }
}
```

---

## 4. Single Backtest on Held-Out Test Data

**Run once.** Parameters locked before test. No re-runs, no tuning.

### Results

| Metric | Value |
|---|---|
| **SHARPE RATIO** | **-11.3052** |
| **CALMAR RATIO** | **-1.0000** |
| Total trades | 70 |
| Win rate | 15.71% |
| Max drawdown | 9.93% |
| Net PnL | -9,927.57 |
| Gross PnL | -5,473.21 |
| Total costs | 4,454.36 |
| Cost drag | 81.38% of gross PnL |

### Trade Sample
All 70 trades were stop-loss triggered, with most losses -1% to -3% per trade. Only a handful hit the 10-period time-based exit (SIGNAL). The strategy was consistently wrong direction, entering longs before drops and shorts before rallies.

### Alternative Strategy Comparison (Test Data)

| Strategy | Sharpe | Calmar | Trades | Win Rate |
|---|---|---|---|---|
| Momentum | -11.24 | -1.00 | 70 | 15.7% |
| Mean Reversion | -6.36 | -0.81 | 41 | 19.5% |
| OFI | 0.00 | 0.00 | 0 | 0.0% |
| Combined (weighted, locked) | -11.31 | -1.00 | 70 | 15.7% |
| Combined (equal weights) | -11.40 | -1.00 | 69 | 14.5% |

**No strategy worked.** Mean-reversion was the least bad at -6.36 Sharpe, but still deeply negative.

---

## 5. Sharpe & Calmar Formulas

**Sharpe:**
```
rf_per_period = (1.065)^(1/252) - 1 ≈ 0.000250
excess = [r - rf_per_period for r in trade_returns]
sharpe = mean(excess) / stdev(excess) * sqrt(252)
```
- Annualization factor: 252 periods/year
- Risk-free rate: 6.5% (Indian risk-free proxy — G-sec ~6.5%)
- Returns used: per-trade returns, not daily mark-to-market

**Calmar:**
```
calmar = (total_pnl / initial_capital) / max_drawdown
```
- `initial_capital` = 100,000.0
- `max_drawdown` = peak-to-trough decline as fraction of peak equity

---

## 6. Transaction Costs

**Included: Yes.** The `CostModel` applies to every trade:

| Component | Value | Applied To |
|---|---|---|
| Market impact (k × sqrt(Qty/ADV) × P × Q) | k=0.0015 | Every trade |
| Spread cost (half-spread × P × Q) | From snapshot spread_bps | Every trade |
| Brokerage | Rs 20/trade | Every trade |
| STT (Securities Transaction Tax) | 0.1% on sells | Sell orders only |

**ADV lookup:** Empty (no daily volume data was pre-configured). The CostModel handles this with a default path — impact is still calculated using fallback values.

**Cost drag:** 81.38% of gross PnL. The strategy's gross PnL was already negative (-5,473), and costs added another -4,454, making the net loss nearly double the gross loss.

---

## 7. Trade Count & Statistical Confidence

- **Total trades:** 70
- **Assessment:** Moderate count, but the Sharpe has high variance. At 70 trades with 15.7% win rate, the negative Sharpe is robust in direction (clearly loss-making) but the exact magnitude (-11.3 vs -8.0) should not be over-interpreted.
- **Signal:** The win rate is consistent across all strategies (14.5%–19.5%), which strongly suggests the underlying issue is not strategy-specific but data-structure-specific (daily data not suitable for these minute-level signals).

---

## 8. Known Limitations

1. **Daily vs. intraday data:** The signals (momentum, mean-reversion, OFI) are designed for tick/minute-level data. On daily bars, the momentum window parameters (1, 5, 15 periods) span 1–15 trading days, and the OFI cannot trigger because bid/ask volumes are inferred symmetrically.
2. **Inferred bid/ask:** Real NSE order book data provides actual bid/ask depth. Yahoo Finance daily OHLCV does not. The 50/50 volume split makes OFI perpetually 0.
3. **Spread estimation:** Daily High-Low range is a proxy for spread, not the actual NSE market spread (which would be tighter for LIQUID symbols like RELIANCE).
4. **Single symbol only:** Tested only RELIANCE. Results on other NSE symbols may differ.
5. **NSGA-II overfitting:** The returns matrix (3 signals × 10 trade observations) was far too small for meaningful optimization (33 degrees of freedom in the optimization). The Pareto front's 8.57 Sharpe on train data was entirely spurious — confirmed by test performance of -11.3.
6. **Cost drag dominance:** At 81% cost drag, costs dominate PnL. A profitable strategy on daily data needs to hold positions much longer (lower turnover) to let gross returns overcome frictions.

---

## 9. Verification Statement

> **This number came from ONE run on held-out data, parameters locked before seeing test results.**
> No deviations from protocol. No re-runs. No parameter tweaks after seeing test output.

The selection rule was pre-committed in the script before execution. The locked parameters JSON was persisted before Phase 3 ran.

---

## 10. Comparison to Prior Claims

| Claim | Prior Reported | Actual (This Run) | Verdict |
|---|---|---|---|
| Sharpe | 1.70 | -11.31 | Never verified on real data; synthetic-only or never run |
| Calmar | 3.33 | -1.00 | Never verified on real data |
| Strategy works on NSE data | Implied | Does not work in this form | Strategy signals designed for intraday; daily data incompatible |

The previously claimed 1.70 Sharpe / 3.33 Calmar were never produced from a real backtest on historical market data. This run is the first end-to-end, verifiable backtest using real NSE data with locked parameters and a single held-out test run. The result is negative, which is the honest outcome.
