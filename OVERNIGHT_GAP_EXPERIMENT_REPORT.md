# AlphaCore — Overnight Gap & Post-Earnings-Announcement Drift Experiment Report

**Date:** July 30, 2026 — 20:15 IST  
**Protocol:** `OVERNIGHT_GAP_EXPERIMENT_PROTOCOL.md` (pre-committed 2026-07-30 19:45 IST)  
**Experiment script:** `backend/experiments/overnight_gap_experiment.py`  
**Raw results:** `overnight_gap_results.json`  
**Previous experiments:** Momentum, mean-reversion, OFI (all null); Cross-sectional relative strength (signal skilled but costs destroyed); Monthly cross-sectional (costs still >100%)

---

## ⚠️ HEADLINE LIMITATIONS — READ FIRST

1. **"Intraday" via daily OHLC only.** The overnight gap strategy simulates entering at the open price and exiting at the close price using daily bars. Real intraday execution would involve timing within the day, slippage, partial fills — none of which are modeled. The true intraday PnL would likely be worse.

2. **5-symbol universe unchanged.** The same extreme small-universe limitation applies to both signals.

3. **PEAD data source reliability.** yfinance's `earnings_dates` API is unreliable — it uses HTML scraping that sometimes fails with structural errors (missing columns). HDFCBANK failed to fetch on one attempt, and the API is inconsistent. PEAD results are based on what data was available and should be treated with additional caution.

4. **Cost model double-counts spread.** All experiments in this project use bid/ask prices for entry/exit AND separately apply the CostModel's spread_cost. This means total spread cost is ~4× half-spread per round trip vs. realistic ~2×. Cost figures are systematically conservative (overstated) across ALL experiments, making cross-experiment comparisons valid but absolute cost numbers higher than real-world.

---

## Step 0 Outcome: PEAD Feasibility

yfinance provides `earnings_dates` via `yf.Ticker().earnings_dates` with columns `EPS Estimate`, `Reported EPS`, and `Surprise(%)`. Each symbol returned 25 earnings dates spanning 2020–2026 (24 in our range).

**However**, the API proved unreliable. It uses HTML scraping internally (`_get_earnings_dates_using_scrape`), and repeated calls sometimes fail with `KeyError: 'Earnings Date'` — a structural issue in yfinance's own code. HDFCBANK failed on one run but succeeded on another. **PEAD was tested with the data that was available**, but the data-source reliability limits confidence.

---

## Part A — Overnight Gap Reversal

### 1. Pre-Committed Choices

| Parameter | Choice | Rationale |
|-----------|--------|-----------|
| **Hypothesis** | Gap reversal | Train data showed negative gap-intraday correlation for 4/5 symbols |
| **Threshold** | 1.5% absolute gap | 95th percentile of absolute gaps; captures meaningful events |
| **Entry** | At open (ask for long, bid for short) | First available price after gap observed |
| **Exit** | At close same day (bid for long, ask for short) | Intraday hold |
| **Position size** | 10% of equity per symbol | Consistent with prior experiments |
| **Cost model** | `CostModel()` default | Same as all prior experiments |
| **Multi-symbol** | Independent per symbol | Multiple positions on same day allowed |

### 2. Results

| Metric | Overnight Gap Reversal |
|--------|----------------------|
| **Sharpe** | **-6.80** |
| **95% CI** | **[-5.87, -3.52]** (entirely negative) |
| CI excludes zero? | True (NEGATIVE) |
| **Net PnL** | **-₹17,955.91** (-17.96%) |
| Gross PnL | -₹2,526.90 |
| Total costs | ₹15,429.01 |
| **Cost drag** | **610.6%** |
| Final equity | ₹82,044.09 |
| Trades | 126 (63 long, 63 short) |
| Win rate | 46.8% (59/126) |
| Reversal correct | **46.8%** (gap reversed correctly less than half the time) |

### 3. Per-Symbol Breakdown

| Symbol | Trades | PnL | Win Rate | Avg Gap | Test-Period Return |
|--------|--------|-----|----------|---------|-------------------|
| RELIANCE | 17 | -₹132.61 | 47% | +0.42% | +2.98% |
| TCS | 24 | **+₹137.39** | **58%** | -0.16% | -37.64% |
| INFY | 47 | **-₹2,848.72** | 43% | +0.04% | -35.46% |
| HDFCBANK | 21 | +₹248.61 | 43% | -1.03% | -8.74% |
| ICICIBANK | 17 | +₹68.42 | 47% | +0.18% | +15.02% |

### 4. Analysis

The overnight gap reversal strategy failed on all fronts:

**Directional accuracy (46.8%):** The gap did NOT reverse more often than it continued. The 46.8% win rate means the gap was more likely to continue than reverse — the opposite of the hypothesized effect. This was consistent across symbols: only TCS showed above-50% accuracy (58%).

**Cost dominance (610.6%):** With 2 trades per gap event (entry + exit) on each of 126 trades, that's 252 individual transactions. At ~₹60 per trade average cost, the costs dwarf the gross PnL. The average trade lost ₹20 in gross PnL but cost ₹122 to execute.

**INFY dominated the losses:** INFY triggered 47 of the 126 trades (37%), and its -₹2,849 loss accounts for 113% of the total gross loss. INFY's high volatility generated many gap-trigger events, and the gap reversal pattern was weakest for INFY (mean correlation of +0.0008 on train data — the only symbol without negative correlation).

**Observation:** The gap reversal hypothesis was incorrect for this data. The data shows slight **gap continuation** (gaps tend to continue intraday more often than reverse). A gap-continuation strategy would also need to survive the same cost structure — and with 610.6% cost drag, the direction doesn't matter enough to overcome costs.

---

## Part B — Post-Earnings-Announcement Drift (PEAD)

### 1. Pre-Committed Choices

| Parameter | Choice |
|-----------|--------|
| **Hypothesis** | Post-earnings-announcement drift in the direction of the surprise |
| **Surprise threshold** | \|Surprise\| > 5% |
| **Holding period** | 10 trading days |
| **Entry** | At close on announcement date |
| **Exit** | At close 10 trading days later |
| **Position size** | 10% of equity per event |

### 2. Results

| Metric | PEAD |
|--------|------|
| **Net PnL** | **-₹4,621.56** |
| Gross PnL | -₹833.15 |
| Total costs | ₹3,788.41 |
| **Cost drag** | **454.7%** |
| Events | 30 (6 per symbol) |
| Win rate | 43.3% (13/30) |

### 3. Per-Symbol Breakdown

| Symbol | Events | Gross PnL | Win Rate | Avg Surprise |
|--------|--------|-----------|----------|-------------|
| RELIANCE | 6 | -₹918.95 | 33% | +18.2% |
| TCS | 6 | +₹1.41 | 33% | +1.1% |
| INFY | 6 | **+₹411.98** | **67%** | +4.6% |
| HDFCBANK | 6 | +₹381.25 | 33% | +4.5% |
| ICICIBANK | 6 | -₹708.85 | 50% | +2.4% |

### 4. Analysis

PEAD also failed to produce positive returns:

**Directional accuracy (43.3%):** Even with the 5% surprise threshold, the post-earnings drift was correct only 43.3% of the time — worse than random. Only INFY showed a positive win rate (67%).

**Cost dominance (454.7%):** Same pattern as every other signal — costs overwhelm any signal edge. With 5% position sizing and 10-day holds, each event generates 2 trades (entry + exit) at ~₹60 each.

**Small sample (30 events):** The PEAD sample is small (only 6 events per symbol), limiting statistical power. But the consistency with every other signal tested (negative PnL, cost-dominated) makes it unlikely that a larger sample would reverse the result.

**Data quality note:** The yfinance earnings_dates API uses HTML scraping that is unreliable. Some symbols failed on some runs but succeeded on others. The 5% surprise threshold was meant to capture meaningful events, but the average surprises per symbol (1.1%–18.2%) suggest the threshold may have been too high for some symbols (TCS avg 1.1% means few qualifying events). However, lowering the threshold would increase trade count but also include noise — the net effect is unclear.

---

## 5. Overall Arc: Seven Tests Across Four Signal Families

This experiment marks the **sixth and seventh signal tests** on this 5-symbol NSE daily dataset:

| # | Signal | Result |
|---|--------|--------|
| 1 | Momentum + MR + OFI (single-symbol) | Sharpe -11.3, cost-dominated |
| 2 | NSGA-II vs equal weights (synthetic GBM) | Null — both unprofitable |
| 3 | NSGA-II vs equal weights (real data) | Null — all CIs include zero |
| 4 | Cross-sectional relative strength (5-day) | Signal skilled (61%/72%), 243% cost drag destroyed edge |
| 5 | Cross-sectional relative strength (monthly) | Cost drag 123.8% still >100%, still negative |
| 6 | **Overnight gap reversal (this)** | **Sharpe -6.80, cost drag 610.6%, signal wrong (46.8%)** |
| 7 | **PEAD (this)** | **Net -₹4,622, cost drag 454.7%, win rate 43.3%** |

All seven tests have failed to find a profitable, cost-surviving strategy. The most promising signal family (cross-sectional relative strength, #4 and #5) showed genuine directional skill but could not survive transaction costs even at monthly rebalancing due to the small universe.

---

## 7. Closing Reflection

> **Does overnight gap reversal (or PEAD) show a real, cost-surviving edge on this 5-symbol daily NSE data?**

**ANSWER: No. Both signals fail. Overnight gap reversal loses money with statistical significance (Sharpe -6.80, CI entirely negative), and PEAD loses money net of costs (-₹4,622).**

The overnight gap result is particularly definitive: the hypothesized reversal pattern does not exist in this data (the data shows slight continuation), and even if it did, the 610.6% cost drag would destroy any edge.

**This is now the cleanest convergence in the project.** Six independent signal families — momentum, mean-reversion, OFI, cross-sectional relative strength (two frequencies), overnight gap, and PEAD — have all failed on this specific dataset. The most likely explanation is no longer "we haven't found the right signal." It is that **the combination of a 5-symbol universe, daily-bar granularity, and realistic transaction costs for these specific large-cap NSE stocks does not support any profitable systematic strategy at the tested horizons.**

The remaining levers for finding an edge on this market would require:
1. **A larger universe** (100+ symbols) — for cross-sectional strategies to work
2. **Higher-frequency data** (tick/minutes) — for microstructure effects
3. **A different market segment** (small/mid-cap) — where inefficiencies are larger
4. **Better data** (real order book depth, not daily OHLC proxies)

Further signal exploration on this specific 5-symbol daily dataset is unlikely to produce a different outcome.

---

## 8. Files Produced

- `OVERNIGHT_GAP_EXPERIMENT_PROTOCOL.md` — pre-committed protocol
- `backend/experiments/overnight_gap_experiment.py` — experiment script
- `OVERNIGHT_GAP_EXPERIMENT_REPORT.md` — this document
- `overnight_gap_results.json` — raw results

---

*Protocol was written before any test-period evaluation was executed. All parameter choices were pre-committed. The PEAD portion was tested as secondary per Step 0 feasibility; data-source reliability limitations are noted above.*
