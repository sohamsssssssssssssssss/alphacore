"""Microstructure analytics endpoints."""

from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter

from data.scheduler import liquidity_scorer, spread_tracker, vwap_engine
from engines.market_impact import ADV_BY_SYMBOL, market_impact_model

router = APIRouter(prefix="/api/microstructure", tags=["microstructure"])

TRACKED_SYMBOLS = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]


class ImpactBody(BaseModel):
    symbol: str
    qty: int
    side: str


@router.get("/vwap/{symbol}")
async def get_vwap(symbol: str) -> dict:
    all_vwaps = vwap_engine.get_all(symbol)
    current_price = spread_tracker.get_spread(symbol).get("mid", 0.0)
    return {
        "symbol": symbol.upper(),
        "vwap_1min": all_vwaps.get("1min"),
        "vwap_5min": all_vwaps.get("5min"),
        "vwap_15min": all_vwaps.get("15min"),
        "vwap_session": all_vwaps.get("session"),
        "current_deviation_bps": vwap_engine.get_vwap_deviation(symbol, current_price) if current_price else 0.0,
    }


@router.get("/spread/{symbol}")
async def get_spread(symbol: str) -> dict:
    spread = spread_tracker.get_spread(symbol)
    return {
        "symbol": symbol.upper(),
        "bid": spread.get("bid", 0.0),
        "ask": spread.get("ask", 0.0),
        "spread_abs": spread.get("absolute", 0.0),
        "spread_bps": spread.get("relative", 0.0),
        "mid": spread.get("mid", 0.0),
        "avg_spread_bps": spread_tracker.get_avg_spread(symbol, window=60),
        "history": spread_tracker.get_spread_history(symbol, n=60),
    }


@router.get("/liquidity")
async def get_liquidity() -> list[dict]:
    rows = [
        {"symbol": symbol, **score}
        for symbol, score in liquidity_scorer.get_all_scores().items()
    ]
    return sorted(rows, key=lambda x: x.get("total", 0.0), reverse=True)


@router.get("/liquidity/{symbol}")
async def get_symbol_liquidity(symbol: str) -> dict:
    return {"symbol": symbol.upper(), **liquidity_scorer.get_score(symbol)}


@router.post("/impact")
async def get_impact(body: ImpactBody) -> dict:
    symbol = body.symbol.upper()
    adv = ADV_BY_SYMBOL.get(symbol, 1_000_000)
    spread_bps = spread_tracker.get_spread(symbol).get("relative", 10.0) or 10.0
    reference_price = spread_tracker.get_spread(symbol).get("mid", 2500.0) or 2500.0
    impact = market_impact_model.total_impact(body.qty, adv=adv, spread_bps=spread_bps, reference_price=reference_price)
    curve = market_impact_model.price_impact_curve(adv=adv, spread_bps=spread_bps, max_qty_pct=0.10)
    return {
        "symbol": symbol,
        "qty": int(body.qty),
        **impact,
        "impact_curve": curve,
    }


@router.get("/summary")
async def get_summary() -> list[dict]:
    rows = []
    for symbol in TRACKED_SYMBOLS:
        vwaps = vwap_engine.get_all(symbol)
        spread = spread_tracker.get_spread(symbol)
        liq = liquidity_scorer.get_score(symbol)
        rows.append(
            {
                "symbol": symbol,
                "vwap_5min": vwaps.get("5min"),
                "spread_bps": spread.get("relative", 0.0),
                "liquidity_grade": liq.get("grade", "F"),
                "liquidity_total": liq.get("total", 0.0),
            }
        )
    return rows
