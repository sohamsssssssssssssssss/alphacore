# K=12 basket provenance audit — 2026-11-13

Source: read-only `alphacore-main/backend/sandbox/` export. Neither old folder
contains Git metadata. Inventory compared both exports against fresh main
`66dba39`; source hashes and timestamps describe files, not pre-registration.
The original hypothesis text is preserved in `K12_BASKET_HYPOTHESIS.md`.
The script is imported into `backend/experiments/basket_backtest.py`; its
imports and hypothesis lookup were adjusted for the new location only.
No standalone basket report or raw basket result JSON was found in either
export. The result occurs as narrative assertions in hypothesis.md, README.md,
basket_hypothesis.py and sandbox session log headers. Those repeated assertions
are not independent results or a reproducible return series.

## a) Protocol and chronology

A protocol-like file is present: `K12_BASKET_HYPOTHESIS.md`, copied verbatim
from the source hypothesis.md. Its source filesystem birth time is
2026-08-13T15:05:10+0530 and mtime is 2026-08-13T19:09:58+0530. The source
basket_backtest.py birth time is 2026-08-13T15:06:18+0530 and mtime is
2026-08-13T19:44:13+0530. The hypothesis document includes both the proposed
experiment and already-computed results. No original protocol commit or raw
result timestamp exists to compare. A filesystem birth time cannot prove the
contents were fixed then. Pre-registration is unverified: label this result
**exploratory, not pre-registered**.

## b) Metric recomputation

Quoted: Sharpe **0.6610**; 95% CI **[0.5718, 1.9514]**.
Recomputed: **unavailable**; raw result JSON and original period_returns were
not found. Equality to the quotation is **not established**. Do not quote the
figure as a verified result or substitute a newly fetched-data run for it.

The script calls `compute_sharpe(period_returns, periods_per_year=12)` and
`stationary_bootstrap_sharpe_ci(period_returns, periods_per_year=12)`.
Canonical defaults are a Politis–Romano stationary block bootstrap, 1,000
resamples, geometrically distributed blocks of mean length 10, seed 42,
95% percentile interval (2.5th/97.5th percentiles). The point computation
subtracts an annual risk-free rate of 0.065; the bootstrap computes mean/std
without subtracting it. Thus the reported point and CI use different Sharpe
definitions. A point near the lower bound is compatible with that discrepancy
and with asymmetric bootstrap distributions, but does not validate this
particular CI. These definitions have not been changed.

## c) Period and selection bias

The imported hypothesis states 2020-08-14 through 2026-08-13. Earlier daily
experiments used 2021-07-30 through 2026-07-30, with a held-out daily segment
2025-01-31 through 2026-07-30 (`cross_sectional_results.json`, data).
These are **not identical periods**, but overlap heavily. The basket is an
additional configuration pursued after the nine earlier failures; the source
also compares monthly/quarterly cadences and several k/lookback neighbours.
This is subject to multiple-testing/selection bias and needs fresh
out-of-sample data before any claim. No untouched holdout is evidenced.
The historical universe differs too: the basket excludes SBILIFE and reports
TATAMOTORS failing, while earlier NIFTY50 results include SBILIFE and exclude
TATAMOTORS. This is not a controlled tenth run on identical inputs.

## d) Costs and shorts

The script instantiates the same `engines.cost_model.CostModel()` defaults
and passes spread_bps=10.0, with per-leg buys and sells of departing long
holdings. It is **long-only**; selling a holding is not a short leg. No short
borrow cost is modeled. The model is shared, but portfolio construction,
spread assumptions and ADV inputs differ from earlier experiments, so cost
comparability is not established by the shared class alone.

## e) Lookahead

The signal filters closes to dates <= rebalance day in
`sandbox/rs_signal.py:trailing_returns`; selection delegates to rank_table.
The script executes after the ranking close, on the next available session.
So the **signal** uses only data <= rebalance day. This is not a clean bill
of health for the whole backtest: `sandbox/prices.py:fetch_daily_bars` computes
one ADV from the final 63 sessions of the complete fetched window, then
simulate reuses it for every historical rebalance. Historical transaction
costs therefore use future liquidity information. Current-universe and
adjusted-price history also do not establish point-in-time universe safety.
No strategy, cost or signal logic was changed to address these limitations.

## Verdict

The numerical claim is unsupported by a recoverable raw result artifact.
Keep the README headline unchanged. Imported historical assertions are
preserved for provenance, not endorsed. No fresh parameter search or rerun
with changed parameters was performed for this audit.
