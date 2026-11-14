post hoc, exploratory, not pre-registered

# Arm A, corrected analysis (Amendment 1): top-quartile basket, S&P 100, 2010-01 to 2026-10

Defined in `research/OOS_BASKET_AMENDMENT_1.md` (commit `5f7e8ed`) before this run. Run once, with no alternative sizing, costs or benchmark tried. Raw output: `research/oos/arm_a_corrected.json`.

- Code: `c5f5a07` (`simulate_rebalanced`, `oos_basket.py --mode corrected`). The file records `code_dirty_tracked_files: false`.
- Protocol: `ec9679a`. Universe SHA-256 `a9edcb70…264fc`. Manifest SHA-256 `92c4de2d…a802`. 101 of 101 tickers, 0 unavailable.
- Schedule: 202 month-ends (2010-01-29 to 2026-10-30). Actionable rebalances 2010-04-30 to 2026-09-30 (198). Monthly active returns: 197.
- Skipped rebalances, same for both sides: 2010-01-29, 2010-02-26, 2010-03-31 (no name with a full ADV window), 2026-10-30 (no next session).
- Carried names: 0 on both sides. Skipped buys: 0 on both sides.

## Result

**Outcome (amendment table): no evidence of an edge.** The 95% interval includes zero: [-0.3253, 0.6240].

| Metric | Corrected (amendment 1) | Registered (protocol as written) |
|---|---|---|
| Outcome wording | no evidence of an edge | Fail |
| IR, active monthly returns (mean / std × √12, rf 0) | 0.1638 | -0.8374 |
| 95% CI of IR (stationary bootstrap, 2000 resamples, block 3, seed 2026) | [-0.3253, 0.6240] | [-1.3253, -0.3772] |
| Monthly active returns (n) | 197 | 197 |
| Mean monthly active return | 0.1141% | -0.9994% |
| Months with positive active return | 96 of 197 | 67 of 197 |
| Point IR, basket net | 1.2386 | 1.0744 |
| Point IR, benchmark net | 1.2581 | 1.1757 |

The "Point IR" rows are the basket and benchmark IRs taken alone, not active. The registered column is quoted from `research/oos/ARM_A_RESULT.md`.

## Prediction against actual (stated in amendment 1)

| | Predicted | Actual |
|---|---|---|
| Interval | includes zero, or lies below it | includes zero: [-0.3253, 0.6240] |
| IR point estimate | between -0.6 and +0.1 | 0.1638 (above the stated range) |
| Outcome | "no evidence of an edge" or "not supported" | "no evidence of an edge" |
| Chance of "candidate only" | about 5% | not triggered |

## Exposure (invested fraction = holdings / equity, after fills at each rebalance)

| | Basket | Benchmark |
|---|---|---|
| Min | 0.994990 | 0.994997 |
| Mean | 0.994993 | 0.994997 |
| Max | 0.994997 | 0.994999 |
| Last (2026-09-30) | 0.994994 | 0.994999 |

Cash after fills is aimed at 0.5% of equity, within the amendment's 0–1% band.

## Costs and turnover

| | Basket | Benchmark |
|---|---|---|
| Total modelled costs (currency units) | 1,548,769.88 | 61,386.89 |
| Average turnover after entry (traded notional / equity, per rebalance) | 1.4467 | 0.0501 |
| Equity at 2026-09-30 | 21,695,833.02 | 17,930,003.35 |

Brokerage was set to 0 for this run (amendment 1). Spread is 10 bps. The other `CostModel` defaults are unchanged.
