# Out-of-sample test of the top-quartile basket: protocol

Registered 2026-11-14, before any data named below was fetched or viewed.
The commit that adds this file is the registration record. Any later edit
must be a new commit that states what changed and why; results obtained
before such an edit stay reported.

## Why

The long-only top-quartile basket is the only AlphaCore configuration without
a negative interval, but it was chosen after nine others failed, on
overlapping NSE data, with a cost model that used future liquidity
(`research/K12_BASKET_PROVENANCE.md`). It has never been tested on data that
played no part in choosing it. This protocol is that test. It is run once.

## Strategy (locked, no tuning)

- Signal: 21-session trailing return, ranked across the universe
  (`backend/sandbox/rs_signal.py`, unchanged).
- Selection: top quartile, k = n_ranked // 4, long-only, equal weight at entry.
- Rebalance: monthly, last session of each month. Trade at the next session's open.
- Costs: `engines.cost_model.CostModel()` defaults, spread 10 bps, as in the
  original basket. ADV is **point-in-time**: mean traded value over the 63
  sessions ending on the rebalance day. (The original used one ADV from the
  end of the window; that leak is removed here and not in the original.)
- Budget 1,000,000 in local currency units. No leverage, no shorting.

## Arm A (primary): untouched market, historical

- Universe: S&P 100 members as listed on the day of the fetch. The ticker
  list is committed before any price is fetched.
- Data: Yahoo daily bars, 2010-01-01 to 2026-10-30, fetched once, frozen with
  a checksum manifest under `data_snapshots/`.
- Benchmark: every universe member with data, equal weight, rebalanced on the
  same dates through the same simulator and cost model (k = all).
- Metric: monthly active return = basket net return minus benchmark net return.
  Annualised information ratio IR = mean / std x sqrt(12), no risk-free
  subtraction (a difference of two invested portfolios).
- Interval: 95% stationary bootstrap, 2,000 resamples, mean block 3 months,
  seed 2026.

### Decision rule

| Outcome | Condition |
|---|---|
| Pass | interval lower bound > 0 |
| Fail | interval upper bound < 0 |
| Inconclusive | interval includes 0 |

Only **Pass** counts as support. Inconclusive is not "promising".

### Power, stated in advance

About 200 monthly observations give an interval half-width near 0.5 in IR.
The test can only confirm an edge of roughly IR 0.5 or more. A smaller real
edge will come out inconclusive.

### Prediction, stated in advance

Inconclusive, with the IR point estimate between -0.3 and +0.3. Estimated
chance of Pass: about 10%.

## Arm B (secondary): NSE forward paper test

- Same locked strategy on the existing 49-symbol NSE universe, point-in-time ADV.
- First rebalance: last NSE session of November 2026. Runs through November 2027.
- Each month, before the rebalance, the basket is written to a dated log and
  committed; fills are simulated at the next open with the cost model.
- Reported descriptively every month against the equal-weight benchmark.
  Twelve observations cannot support a significance claim, and none will be made.
- Purpose: check that live operation matches the backtest mechanics, and
  accumulate untouched data.

## What is not allowed

- Changing lookback, k, cadence, costs, universe rule, period or metric after
  seeing any Arm A number.
- Re-running Arm A on a different market or period because the first result
  was disappointing. A new idea needs a new protocol and data not used here.
- Estimated or substituted numbers. If data cannot be fetched, the arm is
  reported as not run.

## Known limits, accepted in advance

- Current index membership applied to the past (survivorship). It affects
  basket and benchmark alike but need not cancel.
- Yahoo adjusted prices; modelled costs, not fills; an NSE-style cost model
  (transaction tax on sells) applied to US stocks, kept for comparability.
- One market per arm.

## Consequences

- Pass: the basket continues in Arm B, and a second untouched market is
  registered as a replication before any real-money step is considered.
- Fail or Inconclusive: the basket is recorded as not supported and retired
  as a candidate. Arm B still runs as an engineering exercise.
