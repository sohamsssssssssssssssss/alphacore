"""Alpha signal endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request

from api.rate_limit import limiter
from engines.alpha_engine import alpha_engine

router = APIRouter(prefix="/api/alpha", tags=["alpha"])


@router.get("")
@limiter.limit("100/minute")
async def get_alpha_all(request: Request) -> list[dict]:
    rows = alpha_engine.get_all()
    return sorted(rows, key=lambda x: abs(float(x.get("combined", {}).get("alpha_score", 50.0)) - 50.0), reverse=True)


@router.get("/signals/{symbol}")
@limiter.limit("100/minute")
async def get_alpha_signals(request: Request, symbol: str) -> dict:
    res = alpha_engine.compute(symbol)
    return {
        "symbol": symbol.upper(),
        "momentum": res.get("momentum"),
        "mean_reversion": res.get("mean_reversion"),
        "order_flow": res.get("order_flow"),
    }


@router.get("/leaderboard")
@limiter.limit("10/minute")
async def get_alpha_leaderboard(request: Request) -> list[dict]:
    rows = []
    for row in alpha_engine.get_all():
        combined = row.get("combined", {})
        confidence = float(combined.get("confidence", 0.0))
        alpha_score = float(combined.get("alpha_score", 50.0))
        strength = abs(alpha_score - 50.0) / 50.0
        rows.append(
            {
                "symbol": row["symbol"],
                "direction": combined.get("combined_direction", "FLAT"),
                "alpha_score": alpha_score,
                "confidence": confidence,
                "strength": strength,
                "rank_score": confidence * strength,
                "liquidity_grade": row.get("liquidity_grade", "F"),
                "weights": combined.get("weights_used", {}),
            }
        )
    return sorted(rows, key=lambda x: x["rank_score"], reverse=True)


@router.get("/{symbol}")
@limiter.limit("100/minute")
async def get_alpha(request: Request, symbol: str) -> dict:
    return alpha_engine.compute(symbol)
