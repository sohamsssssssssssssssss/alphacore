# Arm A result: top-quartile basket, S&P 100, 2010-01 to 2026-10

Run once. No parameter was changed and no rerun was made. The run did not crash, so no fix was applied.

- Protocol: `research/OOS_BASKET_PROTOCOL.md`, commit `ec9679a` (merged to main via PR #9, merge `8ee162c`).
- Code: `07a74b7` (T1-T2, point-in-time ADV and runner). The run was made at HEAD `7579799`, which adds only the universe, manifest and freeze script. No code changed between them (`code_dirty_tracked_files: false`).
- Universe: `data_snapshots/us-2026-11/universe.txt` (commit `11898dd`), retrieved 2026-11-14T16:50:55Z from https://en.wikipedia.org/wiki/S%26P_100. Universe SHA-256 `a9edcb70c6eafc8c1b14018cf12ca26525a05656aaff9d2ef9635b8c598264fc`.
- Data: Yahoo daily bars fetched once, 2026-11-14 16:51:30 to 16:52:32 UTC, yfinance 1.3.0, auto_adjust. Manifest SHA-256 `92c4de2da39e6bb817de4fb34eee414344d077cd02cc19130395e0267308a802` (commit `7579799`). Data window 2010-01-04 to 2026-10-30. 101 of 101 tickers loaded, 0 unavailable.
- Run: 2026-11-14 16:52:48 to 16:52:56 UTC, `python3.11 -m experiments.oos_basket`, output `research/oos/arm_a.json`.

## Outcome

**Fail.** The 95% interval for IR lies entirely below 0 (upper bound -0.3772).

## Raw numbers

| Field | Value |
|---|---|
| Active monthly returns (n) | 197 |
| IR, active (mean/std x sqrt 12, no rf) | -0.8374 |
| 95% CI, stationary bootstrap (2000, block 3, seed 2026) | [-1.3253, -0.3772] |
| Mean monthly active return | -0.9994% |
| Std of monthly active return (population) | 4.134% |
| Months with positive active return | 67 of 197 |
| IR of basket net returns (point) | 1.0744 |
| IR of benchmark net returns (point) | 1.1757 |
| Basket modelled costs (currency units) | 430,346.96 |
| Benchmark modelled costs (currency units) | 2,586.04 |
| Basket average legs per rebalance | 34.48 |
| Basket average one-sided turnover | 0.7266 |
| Benchmark average legs per rebalance | 0.0609 |
| Benchmark average one-sided turnover | 0.00032 |

Budget is 1,000,000 in local currency units, as the protocol states. Costs are in the same units. The first actionable rebalance is 2010-04-30 and the last is 2026-09-30.

Full monthly basket, benchmark and active returns, the basket sizes, and the eligible-name count at each date are in `research/oos/arm_a.json`.

## Pre-registered prediction next to the actual

| | Pre-registered (protocol, "Prediction") | Actual |
|---|---|---|
| Outcome | Inconclusive | Fail |
| IR point estimate | between -0.3 and +0.3 | -0.8374 |
| Chance of Pass | about 10% | not applicable (outcome is Fail) |

## Schedule

- Month-ends in the snapshot: 202, from 2010-01-29 to 2026-10-30.
- Skipped: 2010-01-29, 2010-02-26 and 2010-03-31, where no name had a full 63-session ADV window. 2026-10-30, where no next session exists in the data.
- Actionable rebalances: 198, from 2010-04-30 to 2026-09-30. That gives 197 monthly active returns.

## Implementation decisions

These were made in T1-T2, before any US price was fetched (commit `07a74b7`).

1. **Eligibility.** A name is rankable at a rebalance only if it has a full 63-session point-in-time ADV window at that date. Basket and benchmark use the same rule. Without this rule, `CostModel` silently uses the trade quantity as ADV when ADV is missing, which is a substituted impact cost, and the protocol forbids substitution. Eligible-name counts per date are in `arm_a.json` (`eligible_counts`). The rule matters for late listings in the window, for example GEV from 2024-03-27, SNDK from 2025-02-13, PLTR from 2020-09-30 and UBER from 2019-05-10. The protocol does not address this case explicitly, so this is an interpretation. The rule was fixed before the data was fetched, but it is still an interpretation.
2. **Basket size.** k = n_ranked // 4, where n_ranked counts eligible ranked names. It ranges from 22 (2010-04-30) to 25 (2026-09-30).
3. **Benchmark.** All eligible ranked names, equal weight at entry, traded through the same simulator and cost model.
4. **Bootstrap.** The existing `engines.backtest_metrics.stationary_bootstrap_sharpe_ci` is used with periods_per_year 12 and risk_free 0. Its point estimate equals the IR to within 1e-12, which the runner checks. No new resampler was written.
5. **Standard deviation** is population (ddof 0), as in the repository's metric code.

## Known limits (from the protocol, accepted in advance)

- Current S&P 100 membership is applied to the past (survivorship). It affects basket and benchmark alike but need not cancel.
- Yahoo adjusted prices. Costs are modelled, not fills. An NSE-style cost model (transaction tax on sells) is applied to US stocks for comparability.
- One market per arm.
- Power: about 200 monthly observations give an IR interval half-width near 0.5. The test can only confirm an edge of IR 0.5 or more.

## Consequence (protocol, "Consequences")

Fail or Inconclusive: the basket is recorded as not supported and retired as a candidate. Arm B still runs as an engineering exercise.
