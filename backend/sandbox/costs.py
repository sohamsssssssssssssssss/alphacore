"""
Cost baselines for the sandbox cost-comparison report.

BACKTEST-ASSUMED costs = the repo CostModel defaults
(backend/engines/cost_model.py: k_impact=0.0015, brokerage_per_trade=20.0,
stt_rate=0.001). This module is a STATIC MIRROR of those parameters and
formulas so the sandbox package stays isolated from the live trading path;
if engines/cost_model.py defaults change, this file must be updated (the
report prints the exact parameters it used on every run, so drift is visible).

ASSUMED_SPREAD_BPS is the one parameter the repo CostModel leaves to callers;
the research backtest used a 10 bps half-spread assumption, so 10.0 is used
and printed as an assumption on every run.

Sandbox-OBSERVED costs are NOT computed here from fills (fills are only
logged verbatim from the API); this module only converts raw fill evidence
into bps figures when the API actually returns one.
"""

from __future__ import annotations

import math
from typing import Any

# Backtest-assumed parameters (mirror of engines.cost_model.CostModel defaults).
K_IMPACT = 0.0015
BROKERAGE_PER_TRADE_INR = 20.0
STT_RATE = 0.001  # charged on sell side only
ASSUMED_SPREAD_BPS = 10.0  # half-spread assumption; printed on every report run

BACKTEST_ASSUMED_COST_PARAMS: dict[str, float] = {
    "k_impact": K_IMPACT,
    "brokerage_per_trade_inr": BROKERAGE_PER_TRADE_INR,
    "stt_rate": STT_RATE,
    "assumed_spread_bps": ASSUMED_SPREAD_BPS,
}


def market_impact(price: float, qty: float, adv: float | None) -> float:
    if qty <= 0 or price <= 0:
        return 0.0
    eff_adv = float(adv) if adv is not None and adv > 0 else float(qty)
    return float(max(0.0, K_IMPACT * math.sqrt(float(qty) / eff_adv) * float(price) * float(qty)))


def spread_cost(price: float, qty: float, spread_bps: float = ASSUMED_SPREAD_BPS) -> float:
    if qty <= 0 or price <= 0:
        return 0.0
    return float(max(0.0, (float(spread_bps) / 10000.0) / 2.0 * float(price) * float(qty)))


def assumed_total_cost(price: float, qty: float, adv: float | None, side: str) -> float:
    """Backtest-assumed total cost in INR for one leg (matches CostModel.total_cost)."""
    if qty <= 0 or price <= 0:
        return 0.0
    stt = STT_RATE * float(price) * float(qty) if side.upper() == "SELL" else 0.0
    return float(max(
        0.0,
        market_impact(price, qty, adv)
        + spread_cost(price, qty)
        + BROKERAGE_PER_TRADE_INR
        + stt,
    ))


def cost_in_bps(cost_inr: float, price: float, qty: float) -> float:
    """Convert an INR cost to basis points of traded notional."""
    notional = float(price) * float(qty)
    if notional <= 0:
        return 0.0
    return float(cost_inr / notional * 10000.0)


def observed_slippage_bps(fill_price: float, ref_price: float, side: str) -> float:
    """
    Slippage in bps of the fill vs the reference price.

    BUY: positive = paid more than reference (adverse). SELL: positive =
    received less than reference (adverse).
    """
    if ref_price <= 0 or fill_price <= 0:
        return 0.0
    raw = (float(fill_price) - float(ref_price)) / float(ref_price) * 10000.0
    return float(raw if side.upper() == "BUY" else -raw)


def extract_observed_fill(raw_response: Any) -> dict[str, Any]:
    """
    Pull whatever fill evidence the raw sandbox response actually contains.

    Returns keys: fill_price, fill_qty, fill_timestamp, observed_fees_inr,
    source_field. Returns all-None if the response has no fill data — the
    harness then records fill_status=UNCONFIRMED instead of inventing fills.
    """
    out: dict[str, Any] = {
        "fill_price": None,
        "fill_qty": None,
        "fill_timestamp": None,
        "observed_fees_inr": None,
        "source_field": None,
    }
    data = raw_response if isinstance(raw_response, dict) else None
    if not data:
        return out
    payload = data.get("data") if isinstance(data.get("data"), dict) else {}

    for key in ("average_price", "trade_price", "fill_price"):
        val = payload.get(key)
        if val is not None:
            try:
                out["fill_price"] = float(val)
                out["source_field"] = key
                break
            except (TypeError, ValueError):
                continue
    for key in ("filled_quantity", "trade_quantity", "fill_qty"):
        val = payload.get(key)
        if val is not None:
            try:
                out["fill_qty"] = float(val)
                break
            except (TypeError, ValueError):
                continue
    for key in ("fill_timestamp", "trade_timestamp", "exchange_timestamp"):
        val = payload.get(key)
        if val is not None:
            out["fill_timestamp"] = str(val)
            break
    for key in ("fees", "total_charges", "brokerage"):
        val = payload.get(key)
        if val is not None:
            try:
                out["observed_fees_inr"] = float(val)
                break
            except (TypeError, ValueError):
                continue
    return out
