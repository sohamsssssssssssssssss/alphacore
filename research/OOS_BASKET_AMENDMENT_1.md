# Amendment 1 to the out-of-sample basket protocol

Written 2026-11-14, after the registered Arm A run and after its exposure
diagnostic, before any corrected number exists. The registered result is not
changed by this file.

## What happened

Arm A ran once as registered: IR -0.8374, 95% interval [-1.3253, -0.3772],
outcome **Fail** (`research/oos/ARM_A_RESULT.md`). That stays on record.

The run did not measure what the protocol described:

- The simulator buys each new position at a fixed size from the starting
  budget and never tops up. The basket's invested share fell from 1.00 to
  0.20 over the window (mean 0.49); the rest sat in cash earning nothing.
- The benchmark bought once and held. It was not rebalanced on the same
  dates, as the protocol required, and ended with 25% in one stock.

So a mostly-cash basket was compared with a fully invested, drifting
benchmark in a rising market. The protocol author specified "reuse the
simulator unchanged" without checking its sizing. That was the error.
The same simulator produced the NSE K=12 figures (invested share 0.99
falling to 0.47).

## Corrected analysis (post hoc, exploratory)

Everything in the protocol's "Strategy" section stays, except sizing and costs
as stated here. A new simulator function is used for basket and benchmark alike:

- At every rebalance, every member is set to equal weight of current equity
  (1/k each), trading the differences at the next session's open. Fractional
  shares. Fully invested: cash after fills is between 0 and 1% of equity.
- Benchmark: all eligible names, same function, same dates, k = all.
- Costs on traded notional: spread, impact (point-in-time ADV) and the
  sell-side tax, as before. **Flat per-trade brokerage is set to 0 for the US
  run.** At this budget a flat fee on about 100 small monthly trades would
  penalise the benchmark for an arbitrary account size. Removing it favours
  the benchmark relative to the basket, which trades fewer names.
- Eligibility rule, universe, frozen data, period, metric, bootstrap settings
  and seed: unchanged from the registered run.

### Status and wording

This run is made after seeing a result on the same data. It cannot produce
"Pass". Its outcomes are:

| Interval of IR | Wording | Consequence |
|---|---|---|
| upper bound < 0 | not supported, also after correction | basket retired |
| includes 0 | no evidence of an edge | basket retired |
| lower bound > 0 | candidate only | a new protocol on a second untouched market, with this simulator, before any claim |

It is run once. No other sizing rule, cost setting or benchmark is tried.

### Prediction, stated in advance

Interval includes zero or lies below it; IR point estimate between -0.6 and
+0.1. A one-month lookback is the horizon where short-term reversal, not
momentum, is the documented effect in US stocks. Estimated chance of
"candidate": about 5%.

## NSE restatement (in-sample, descriptive)

The K=12 basket is re-run on the frozen NSE snapshot with the same corrected
function, point-in-time ADV, and the unchanged `CostModel()` defaults
(including brokerage, which is a real per-order fee on NSE), against the
equal-weight benchmark from the same function. This data was used to choose
the basket, so the restated figures are descriptive only. They replace the
basket row and benchmark comparison in the technical report, with the old
figures kept in the errors section.

## Arm B

Uses the corrected function. Otherwise unchanged.
