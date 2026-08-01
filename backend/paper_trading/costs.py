"""Cost measurement: realized slippage vs. the backtest's cost model.

The backtest assumed, per trade (backend/engines/cost_model.py):
    cost = market_impact(k=0.0015, ADV=qty fallback) + half-spread
         + ₹20 brokerage + 0.1% STT on sells

The paper harness measures REALIZED slippage:
    buy  slippage_bps = (fill - ref_mid)/ref_mid * 1e4   (positive = adverse)
    sell slippage_bps = (ref_mid - fill)/ref_mid * 1e4

where ref_mid is the LIVE bid/ask midpoint recorded at order submission.
Brokerage/STT are deterministic fees — computed, not measured.

Modeled spread for the same trade uses the LIVE measured spread (clamped to the
backtest's [0.5, 50] bps window) so the comparison is apples-to-apples.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engines.cost_model import CostModel  # noqa: E402

_MODEL = CostModel()
_SPREAD_CLAMP = (0.5, 50.0)


def spread_bps(bid: float | None, ask: float | None, mid: float | None) -> float | None:
    if bid is None or ask is None or not mid or ask <= bid:
        return None
    bps = (ask - bid) / mid * 10000.0
    lo, hi = _SPREAD_CLAMP
    return max(lo, min(hi, bps))


def realized_slippage_bps(fill_price: float, ref_mid: float, side: str) -> float:
    """Adverse-positive slippage in bps. side is BUY or SELL (order side)."""
    if ref_mid <= 0:
        return 0.0
    if side.upper() == "BUY":
        return (fill_price - ref_mid) / ref_mid * 10000.0
    return (ref_mid - fill_price) / ref_mid * 10000.0


def realized_slippage_rs(fill_price: float, ref_mid: float, side: str, qty: int) -> float:
    if qty <= 0:
        return 0.0
    if side.upper() == "BUY":
        return (fill_price - ref_mid) * qty
    return (ref_mid - fill_price) * qty


def modeled_cost_rs(price: float, qty: int, spread_bps_val: float | None, side: str) -> float:
    """Backtest-cost for the same order (₹). Returns 0 for degenerate inputs."""
    if price <= 0 or qty <= 0:
        return 0.0
    return _MODEL.total_cost(price=price, qty=float(qty), adv=None,
                             spread_bps=spread_bps_val or _SPREAD_CLAMP[0],
                             side=side)


def modeled_slippage_bps() -> float:
    """Per-trade slippage assumption inside the backtest cost model for the
    comparison table: half-spread is the modeled marketable-execution cost
    (execution at ask/bid vs. mid). The model's impact term is separate and
    qty-dependent."""
    return _SPREAD_CLAMP[1] / 2.0  # upper clamp / 2 is a conservative reference
