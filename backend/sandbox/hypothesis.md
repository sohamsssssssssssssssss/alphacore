# PRECOMMITTED HYPOTHESIS — Phase 1, Step 1: Top-Quartile Basket + Rebalance Frequency

**Status: PRE-COMMITTED.** This entry was written BEFORE any backtest for this
task was executed (per the Phase 1, Step 1 brief: hypothesis must exist before
running anything). The basket-config runs below were produced only after this
text was saved. Do not reword retroactively.

## Prior result (reference, already computed — NOT reproduced here)

- Signal: monthly cross-sectional relative strength, 21-day lookback
- Universe: 49 symbols (Nifty 50 minus SBILIFE)
- Selection: K=1 (single best-ranked stock per rebalance)
- Cost model: Repo CostModel, default parameters
- Result: Sharpe **-1.57**, 95% CI **[-3.14, +0.05]**
- Signal has genuine directional skill (60-77% win-alignment) but K=1's
  turnover-to-diversification ratio is the suspected cause of cost dominance.

## Hypothesis (verbatim from the brief, pre-committed before any run)

> If diversification (top-quartile basket, ~12 stocks) is the fix for cost
> drag rather than the signal itself, the basket configs should show Sharpe
> CIs that are clearly positive (lower bound meaningfully above zero, not just
> touching it the way K=1's upper bound touched +0.05). If basket configs
> still show negative or barely-positive-CI Sharpes similar in shape to K=1,
> that indicates the cost problem is structural to the signal family, not
> fixable by basket size alone, and Phase 1 should be treated as a stop
> signal rather than a reason to keep tuning.

## Configs this entry commits to

| Config | Selection | Rebalance | K | Frequencies/yr |
|---|---|---|---|---|
| basket-monthly | top-quartile (k=12 of 49) | last trading day of month | 12 | 12 |
| basket-quarterly | top-quartile (k=12 of 49) | last trading day of quarter-end month | 12 | 4 |

## Methodology commitments (locked before runs, to keep comparability with the 9-config table)

- Signal computation: **unchanged** — `rs_signal.py` 21-day lookback,
  cross-sectional ranking (`rank_table`), selection via existing `top_k(k)`.
- Universe: `UNIVERSE_49` (49 symbols, Nifty 50 minus SBILIFE), unchanged.
- Cost model: **repo `CostModel` defaults** (`k_impact=0.0015`,
  `brokerage_per_trade=20.0`, `stt_rate=0.001` sell-side) with the research
  backtest's assumed 10 bps half-spread (`spread_bps=10.0`), unchanged.
- Returns: per-rebalance-period returns (equity just after fills at end-of-
  period / equity just after fills at start-of-period − 1), annualized with
  the matching factor — periods_per_year=12 for monthly, 4 for quarterly
  (user-confirmed: per-rebalance sampling, NOT daily ×√252).
- Sharpe: `engines/backtest_metrics.compute_sharpe` (repo canonical function).
- 95% CI: `engines/backtest_metrics.stationary_bootstrap_sharpe_ci`
  (Politis–Romano stationary bootstrap — the repo's established CI
  methodology; HANDOFF §6.8), defaults preserved.
- Win-alignment: **beats-market rate** (user-confirmed definition) — % of
  rebalance periods where the equal-weighted basket's gross forward holding-
  period return exceeds the equal-weighted all-universe gross forward return
  over the same window.
- Turnover: average trade legs per rebalance and average one-sided turnover
  fraction (positions changed / basket size).
- Execution convention: fills at the next session's OPEN after each rebalance
  close (the harness's documented AMO / next-session-open semantics); costs
  charged per leg at fill.

---

# PRECOMMITTED HYPOTHESIS — Phase 2: Sanity-Check the Phase 1 Winner Isn't Overfit

**Status: PRE-COMMITTED.** This entry was appended BEFORE any Phase 2 backtest
was executed (per the Phase 2 brief: hypothesis must exist before running
anything). Every Phase 2 run below was produced only after this text was saved.

## Phase 1 reference (already computed, NOT reproduced)

- Top-quartile basket (k=12 of 49), monthly: Sharpe **0.6610**, 95% CI
  **[0.5718, 1.9514]**, win-alignment 45.7% (70 periods) — PRIMARY WINNER.
- Top-quartile basket (k=12 of 49), quarterly: Sharpe **0.5371**, 95% CI
  **[0.4169, 1.4790]**, win-alignment 39.1% (23 periods).
- Data window: 2020-08-14 to 2026-08-13 (49-symbol universe; TATAMOTORS failed
  to fetch via yfinance in Phase 1 and was dropped — 48 ranked, k=12 unchanged).

## Hypothesis (verbatim from the brief, pre-committed before any run)

> If the Phase 1 monthly basket result (Sharpe 0.66, CI [0.57, 1.95]) is
> genuine signal rather than an artifact of this specific 6-year window and
> this specific k=12/lookback=21 pairing, then: (1) splitting the backtest
> period into two halves should show the SAME DIRECTION of result in both
> halves — both positive Sharpe, not one strongly positive and one strongly
> negative; and (2) nudging k (10/12/15) and lookback (18/21/25) by small
> amounts should NOT cause the Sharpe to swing between clearly-positive and
> clearly-negative. If either check fails — a sub-period that's strongly
> negative, or a parameter neighbor that collapses the CI back toward zero
> or below — that is evidence of overfitting, not evidence the strategy
> needs more tuning. This phase's job is to falsify the Phase 1 result, not
> to defend it.

## Commitments for Phase 2 (locked before runs)

- Every Phase 2 run is on the **monthly** cadence with the exact Phase 1
  logic: same `simulate` engine, same repo `CostModel` defaults
  (`k_impact=0.0015`, brokerage Rs 20/trade, STT 0.1% sell-side), same
  10 bps half-spread, same universe, same per-rebalance Sharpe/CI
  methodology (`compute_sharpe` + `stationary_bootstrap_sharpe_ci`,
  periods_per_year=12).
- Win-alignment: same **beats-market** definition as Phase 1 (basket gross
  forward return > equal-weight all-universe gross forward return) — kept
  identical for comparability.
- Split-sample halves by calendar date (not rebalance count): H1 ≈
  2020-08 to 2023-08, H2 ≈ 2023-08 to 2026-08. Each half is an independent
  backtest with a fresh budget; the schedule is clipped to the half's
  window while pre-split price history remains available for the first
  ranking (no lookahead — ranking only ever uses data <= the rebalance
  date, so pre-split history is exactly what a live trader had).
- Sensitivity grid on the FULL window, monthly: k = 10, 12, 15 at
  lookback=21; lookback = 18, 21, 25 at k=12. k and lookback are the ONLY
  variables under test; cost model, universe, win-alignment definition,
  and rebalance schedule stay fixed.
- The center point (k=12, lookback=21) is re-executed for the sensitivity
  table so all rows come from the same data pull (flagged against the
  Phase 1 reference if live data availability shifts, e.g. TATAMOTORS).
- rs_signal.py lookback parameterization must be backward-compatible:
  existing callers that pass no lookback behave identically to today
  (default = LOOKBACK_TRADING_DAYS = 21).
