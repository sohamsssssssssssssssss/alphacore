"""Order flow endpoints for AlphaCore flow analytics."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from engines.flow_engine import flow_engine
from models.schemas import FlowImbalance

router = APIRouter(prefix="/api/flow", tags=["flow"])


@router.get("/{symbol}", response_model=FlowImbalance)
async def get_current_flow(symbol: str) -> FlowImbalance:
    """Return the latest 1-minute flow imbalance for a symbol."""

    flow = flow_engine.get_current_flow(symbol)
    if flow is None:
        raise HTTPException(status_code=404, detail=f"No flow data available for {symbol.upper()}")
    return flow


@router.get("/{symbol}/history", response_model=list[FlowImbalance])
async def get_flow_history(
    symbol: str,
    count: int = Query(default=10, ge=1, le=50),
) -> list[FlowImbalance]:
    """Return recent flow imbalance history for a symbol."""

    history = flow_engine.get_flow_history(symbol, count)
    if not history:
        raise HTTPException(status_code=404, detail=f"No flow history available for {symbol.upper()}")
    return history
