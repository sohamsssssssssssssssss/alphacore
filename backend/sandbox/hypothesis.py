"""
PRECOMMITTED HYPOTHESIS — must be printed by every harness/report run BEFORE
any sandbox data is pulled or any order is placed. Do not delete or reword.

Context (from the K=1 monthly cross-sectional relative-strength research):
  - Nine signal configs across four signal families, backtested on NSE daily
    bars, all negative Sharpe after transaction costs.
  - Best config: K=1 monthly cross-sectional relative strength, Sharpe -1.57,
    95% CI [-3.14, +0.05] on the 49-symbol universe.
  - Cross-sectional relative strength shows genuine directional skill
    (60-77% win-alignment) but is COST-DOMINATED: the signal is real, the
    costs erase it. Universe expansion to 49 symbols improved long-side
    accuracy but did not fix cost drag.

PREDICTION:
    Sandbox-observed execution costs (slippage + any fees the sandbox reports)
    for the same K=1 signal are EXPECTED TO BE HIGHER than the backtest-assumed
    transaction costs (CostModel defaults: k_impact=0.0015, brokerage Rs 20/trade,
    STT 0.1% on sells, 10 bps assumed spread — see costs.py).

Rationale:
    A single-name monthly rotation is the hardest leg to execute cheaply: the
    whole position turns over in one trade per month, so adverse-selection
    slippage on the market order lands on 100% of notional, and there is no
    diversification to amortise fixed costs. The sandbox emulation is not
    expected to systematically beat the backtest's cost assumptions.

Implication:
    This validation is expected to CONFIRM the cost-dominance finding, not
    rescue the -1.57 Sharpe result. If sandbox-observed costs come out LOWER
    than assumed, the hypothesis is falsified and the cost-dominance
    conclusion would need revisiting.

HISTORICAL RECORD: this K=1 hypothesis describes the original single-name
config. The harness now runs the top-quartile basket (k=12) config — the
basket-specific precommitted hypothesis lives in BASKET_HYPOTHESIS_TEXT below
and is what harness.py prints when k != 1 (see harness.basket_hypothesis_header).
This file is imported (not copy-pasted) by harness.py and compare_costs.py so
the hypothesis is guaranteed to be stated before execution.
"""

# K=1 hypothesis (historical record — kept verbatim; the harness printed this
# for the original single-name config).
HYPOTHESIS_TEXT: str = __doc__.strip().splitlines()[0] + "\n\n" + "\n".join(
    __doc__.strip().splitlines()[1:]
)

# Basket-specific precommitted hypothesis (the config the harness now runs:
# top-quartile k=12, monthly rebalance, 21-day lookback). Printed by harness.py
# when k != 1; both are printed if the run mode is ambiguous. Same guard-rail
# convention as the K=1 hypothesis: stated BEFORE any sandbox data is pulled.
BASKET_HYPOTHESIS_TEXT: str = """\
PRECOMMITTED HYPOTHESIS (basket config) — must be printed by the harness run
BEFORE any sandbox data is pulled or any order is placed. Do not delete or reword.

Context (from the Phase 1/2 backtest research on the 49-symbol NSE universe,
Nifty 50 minus SBILIFE):
  - Basket config under test: TOP-QUARTILE basket (k=12 of 49), MONTHLY
    rebalance on the last trading day of each month, 21-trading-day lookback.
  - Backtest result this config validated: Sharpe 0.6610, 95% CI [0.5718,
    1.9514] (per-rebalance returns annualized x12, stationary-bootstrap CI;
    Phase 1 hypothesis bar met — CI lower bound meaningfully above zero).
  - Phase 2 split-sample + parameter-sensitivity checks did not falsify it:
    both halves positive, no parameter neighbour (k 10/12/15, lookback
    18/21/25) collapsed the CI. The edge is time-concentrated (H1 2020-2023
    carried it) and is largely consistent with small-sample noise, but the
    config was NOT falsified.

PREDICTION:
    Sandbox-observed execution costs (slippage + any fees the sandbox reports)
    for the basket config are EXPECTED TO BE CLOSER to the backtest-assumed
    transaction costs than the K=1 case was (CostModel defaults: k_impact=
    0.0015, brokerage Rs 20/trade, STT 0.1% on sells, 10 bps assumed spread —
    see costs.py). Specifically, the per-leg FIXED-cost components (brokerage
    Rs 20/trade, spread) should amortise across the 12 equal-weighted names:
    each leg trades roughly 1/12 of the notional, so fixed costs land on ~8.3%
    of the book per rotation instead of 100%, and only the names the signal
    actually rotates incur them. The per-leg ADV-scaled impact cost
    (k_impact*sqrt(qty/adv)) should still roughly HOLD, because it scales with
    position size, not basket count: a leg that is 1/12 of the budget is still
    a leg, and its impact vs ADV is unchanged by how many siblings it has.

Rationale:
    The K=1 config was the hardest leg to execute cheaply: 100% of notional
    turned over in one trade per month, so every fixed-cost dollar landed on
    the entire position and there was no diversification to amortise anything.
    The basket differs mechanically: equal-weighting splits the budget across
    12 names, so per-trade fixed costs (brokerage, spread) are spread thinner
    per unit of notional, and delta-only rotation (the backtest convention)
    means only names entering/leaving the basket trade at all — the other
    names sit untouched. What does NOT diversify away is impact cost, which is
    a function of each leg's own size relative to its ADV; that component is
    expected to be roughly per-leg as assumed.

Implication:
    CONFIRMS the prediction if sandbox-observed per-leg costs land within/near
    the backtest-assumed per-leg costs (i.e. the basket's assumed-cost baseline
    is a trustworthy estimate of execution reality). FALSIFIES it if
    sandbox-observed costs are systematically HIGHER than assumed (slippage or
    fees materially above the assumed 10 bps spread + impact + brokerage),
    which would mean execution-level costs erode even the diversified basket —
    the same cost-dominance pattern as K=1, just at a smaller scale.
"""


def _boxed_header(title: str, text: str) -> str:
    """Box a precommitted hypothesis in the harness's standard banner."""
    return (
        "=" * 78
        + "\n"
        + title
        + "\n"
        + "=" * 78
        + "\n"
        + text
        + "\n"
        + "=" * 78
    )


HYPOTHESIS_HEADER: str = _boxed_header(
    "PRECOMMITTED HYPOTHESIS (stated before any sandbox data is pulled)",
    HYPOTHESIS_TEXT,
)

BASKET_HYPOTHESIS_HEADER: str = _boxed_header(
    "PRECOMMITTED HYPOTHESIS — BASKET CONFIG (stated before any sandbox data is pulled)",
    BASKET_HYPOTHESIS_TEXT,
)
