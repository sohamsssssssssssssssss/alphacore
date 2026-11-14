# 12-1 momentum on a broad NSE universe: protocol

Registered 2026-11-14, before the universe list or any price named below was
fetched. The commit that adds this file is the registration record. Later
edits must be new commits stating what changed and why.

## Why this, and why now

Every earlier AlphaCore signal used a lookback of about one month on 49 to
100 large stocks. All failed or showed no edge (`research/v2/SUMMARY.md`,
`research/oos/`). One month is the horizon where short-term reversal is the
documented effect. The momentum effect in the literature uses roughly the
past twelve months and skips the most recent one. This protocol tests that
version, once, on stocks this project has not used.

## Strategy (locked)

- Signal: close on the rebalance day's 21st prior session divided by close on
  its 252nd prior session, minus 1 ("12-1"). Ranked across eligible names.
- Selection: top fifth, k = n_eligible // 5, long only.
- Sizing: equal weight of current equity at every rebalance, fully invested
  (`simulate_rebalanced`, the corrected simulator from Amendment 1).
- Rebalance: last NSE session of each month; trade at the next session's open.
- Costs: spread 30 bps, impact with point-in-time 63-session ADV, sell-side
  tax at the `CostModel` default. Flat per-trade brokerage set to 0 for
  basket and benchmark (a flat fee on hundreds of small benchmark trades would
  depend on an arbitrary account size; removing it favours the benchmark).
- Budget 10,000,000 INR. No leverage, no shorting.

## Universe and data

- Nifty 500 constituents as published by NSE Indices on the day of the fetch,
  **minus** the 49 symbols in the existing AlphaCore universe. The ticker list
  and its source URL are committed before any price is fetched.
- Yahoo daily bars, 2009-01-01 to 2026-10-30, fetched once, frozen with a
  checksum manifest. Symbols with no data are listed as unavailable.

### Eligibility at each rebalance (fixed in advance)

A name is rankable only if all hold on the rebalance day:
1. Closes exist for all of the last 253 sessions of the market calendar.
2. A full 63-session point-in-time ADV, and that ADV is at least 10,000,000 INR.
3. No daily close-to-close move above 40% in absolute value within those 253
   sessions (treated as a data error or an unadjusted corporate action).

The benchmark holds every eligible name, equal weight, same simulator, dates
and costs.

## Metric and decision

- Monthly active return = basket net minus benchmark net.
  IR = mean / std x sqrt(12), no risk-free subtraction.
- 95% stationary bootstrap, 2,000 resamples, mean block 3 months, seed 2026.
- Run once.

| Interval of IR | Outcome | Consequence |
|---|---|---|
| lower bound > 0 | Candidate | forward paper test, below |
| includes 0 | No evidence of an edge | retired |
| upper bound < 0 | Not supported | retired |

There is no "Pass". The universe is today's index membership applied to the
past, which removes stocks that fell out of the index and can flatter a
momentum portfolio. A positive interval therefore earns only "Candidate".

### If Candidate

The same locked strategy is paper traded monthly for 24 months with dated,
committed logs written before each rebalance. It is reported descriptively.
No real money is considered before that, and none is implied by this file.

## Power and prediction, stated in advance

- About 190 months gives an interval half-width near 0.5 in IR. An edge
  smaller than about IR 0.5 will come out as "no evidence".
- Prediction: IR point estimate between 0.0 and +0.6. Estimated chances:
  Candidate 25%, no evidence 70%, not supported 5%.

## Not allowed

- Changing lookback, skip, quintile, cadence, costs, eligibility, universe
  rule, period or metric after seeing any number from this data.
- A second run with different settings, or a different market, because the
  first was disappointing. A new idea needs a new protocol and unused data.
- Estimated or substituted numbers.

## Checks required before the real run

The runner must report, and the result file must record, for basket and
benchmark: invested fraction at every rebalance (must stay between 0.99 and
1.00), turnover, total costs, eligible-name count per date. The Amendment 1
flaw was found only after a run; these are checked on synthetic data first
and recorded on the real run.

## Known limits, accepted in advance

Survivorship as above; Yahoo adjusted prices with gaps for smaller stocks;
modelled costs, not fills; assumed spread; one market; the 16-year window
overlaps the 2020-2026 period of earlier experiments in calendar time, though
not in stocks.
