# Overnight Gap & Post-Earnings-Announcement Drift Experiment — Protocol

**Date:** July 30, 2026 — 19:45 IST  
**Status:** **PRE-COMMITTED** — written before any test-period evaluation results were seen  
**Predecessor experiments:** Momentum, mean-reversion, OFI, cross-sectional relative strength (5-day and monthly) — all without profitable, cost-surviving results on this 5-symbol daily dataset.

---

## Why This Task Exists

Five signal families have been tested on this 5-symbol NSE daily dataset without finding a profitable, cost-surviving strategy. This experiment tests two **mechanistically different** signals:

1. **Overnight gap effect (primary):** Whether large overnight returns (gap from previous close to today's open) predict intraday reversals — a microstructure effect distinct from multi-day trend/reversion signals.
2. **Post-earnings-announcement drift / PEAD (secondary):** Whether returns drift in the direction of earnings surprises for days after an announcement.

---

## STEP 0 OUTCOME

- **yfinance earnings_dates:** Available via `yf.Ticker().earnings_dates`. Provides `EPS Estimate`, `Reported EPS`, and `Surprise(%)` columns. Each of the 5 symbols has 25 earnings dates spanning 2020–2026 (24 in our 2021–2026 range). **Clean and usable.**
- **Decision:** PEAD will be tested as a secondary signal.

---

## Part A — Overnight Gap Signal

### 1. Hypothesis

**Gap reversal.** A large positive overnight gap (>1.5%) predicts a *negative* intraday return (open → close). A large negative gap (< -1.5%) predicts a *positive* intraday return.

**Why reversal:** The train-period data shows negative correlation between overnight gap and intraday return for 4/5 symbols:
- ICICIBANK: -0.1065
- HDFCBANK: -0.0534
- RELIANCE: -0.0347
- TCS: -0.0351
- INFY: +0.0008 (essentially zero)

This is consistent with the academic literature on large-cap equity gaps (overreaction to overnight news → mean reversion within the trading day).

### 2. Signal Definition

```
Overnight gap(t) = (Open(t) - Close(t-1)) / Close(t-1)
```

- If gap > +1.5%: SHORT at open (bet on reversal down)
- If gap < -1.5%: LONG at open (bet on reversal up)
- Otherwise: no position

### 3. Gap Threshold

**1.5% absolute gap.** Pre-committed based on train-period analysis:
- 95th percentile of absolute gaps across all symbols = ~1.5%
- Captures the top ~5% of gap events (3-7% of trading days per symbol)
- Sufficient events for statistical power without capturing noise

### 4. Execution

- **Entry:** At the market open price. Long positions enter at ask price; short positions enter at bid price.
- **Exit:** At the same day's close price. Long positions exit at bid price; short positions exit at ask price.
- **Hold period:** Intraday only (one trading day, open to close).
- **Position sizing:** 10% of current equity per position.
- **Multiple positions:** Each symbol is traded independently. Multiple symbols may have positions on the same day.

### 5. Primary Metric

**Sharpe ratio** of daily strategy returns (net of all costs, annualized, 252-day, excess over 6.5% RFR).

### 6. Limitation (Pre-Committed)

**"Intraday" via daily OHLC only.** The strategy simulates entering at the open price and exiting at the close price using daily OHLC bars. Real intraday execution would involve timing within the day, slippage, and partial fills — none of which are modeled. This is a material simplification. The strategy's true intraday PnL would likely be worse than simulated.

---

## Part B — Post-Earnings-Announcement Drift (PEAD)

### 1. Hypothesis

**Post-earnings-announcement drift.** After an earnings announcement with a large surprise (absolute surprise > 5%), the stock's price continues to drift in the direction of the surprise over the subsequent 10 trading days.

### 2. Signal Definition

- Use `Surprise(%)` from yfinance earnings_dates (computed as `(Reported EPS - EPS Estimate) / |EPS Estimate|`)
- If Surprise > +5%: LONG (drift up)
- If Surprise < -5%: SHORT (drift down)
- Threshold of 5% is chosen to capture meaningful earnings surprises while maintaining adequate sample size.

### 3. Holding Period

**10 trading days** after the earnings announcement date (inclusive of the announcement date's close-to-close return? No — entry at close on announcement day, exit at close 10 trading days later).

Actually, to avoid lookahead: the earnings date from yfinance is the announcement date. The strategy enters at the **close of the announcement date** (after the market has had time to react to the announcement) and holds for 10 trading days.

### 4. Execution

- **Entry:** At close of the earnings announcement date (using close price). Long at ask, short at bid.
- **Exit:** At close 10 trading days later. Long exits at bid, short exits at ask.
- **Position sizing:** 10% of current equity per position.

### 5. Limitations (Pre-Committed)

- Small sample size: ~120 total earnings events across 5 symbols (train + test). Only ~36 in test period.
- yfinance Surprise(%) is pre-computed and may use different fiscal periods or estimates than what the market actually reacted to.
- No earnings calendar management — assumes the strategy knows the announcement date at market close on that day (no pre-announcement positioning).

---

## Part C — Shared Configuration

| Parameter | Value |
|-----------|-------|
| Cost model | `CostModel()` default (k=0.0015, ₹20 brokerage, STT 0.1% on sells) |
| Capital | ₹100,000 per signal |
| Train/test split | Chronological 70/30 — same as all prior experiments (Train: 867 rows, Test: 372 rows) |
| Bootstrap | Stationary bootstrap, 2,000 resamples, 95% CI |
| Block length | **5** for both signals (overnight gaps are daily; PEAD holding period is 10 days but gaps between earnings are much longer) |
| Symbols | RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK (same 5) |

The block length of 5 is chosen because:
- Overnight gap trades are daily with no autocorrelation expected (each day is a new gap event)
- PEAD trades are separated by many days between earnings (quarterly ≈ 63 trading days)
- A conservative block of 5 captures any short-term dependency while being small enough to generate adequate bootstrap samples

---

## What Would Invalidate This Run

- Testing both gap continuation and gap reversal and reporting whichever works better
- Changing the gap threshold or PEAD threshold after seeing test results
- Adding a signal filter or secondary condition not pre-committed here
- Changing the holding period for either signal after seeing test results
- Using a different train/test split than every prior experiment

---

*This protocol was written before any test-period evaluation results were computed.*
