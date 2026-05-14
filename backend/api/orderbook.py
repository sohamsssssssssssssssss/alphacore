"""REST order book endpoints for the AlphaCore backend."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from models.schemas import OrderBookSnapshot, SymbolStatus

router = APIRouter(prefix="/api", tags=["orderbook"])


@router.get("/orderbook/{symbol}", response_model=OrderBookSnapshot)
async def get_latest_orderbook(symbol: str, request: Request) -> OrderBookSnapshot:
    """Return the latest order book snapshot for a symbol."""

    snapshot = request.app.state.orderbook_state.get_latest(symbol)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"No order book data available for {symbol.upper()}")
    return snapshot


@router.get("/orderbook/{symbol}/history", response_model=list[OrderBookSnapshot])
async def get_orderbook_history(
    symbol: str,
    request: Request,
    minutes: int = Query(default=30, ge=1, le=60),
) -> list[OrderBookSnapshot]:
    """Return recent historical snapshots for a symbol."""

    history = request.app.state.orderbook_state.get_history(symbol, minutes)
    if not history:
        raise HTTPException(status_code=404, detail=f"No order book history available for {symbol.upper()}")
    return history


@router.get("/symbols", response_model=list[SymbolStatus])
async def list_symbols(request: Request) -> list[SymbolStatus]:
    """Return active symbols and their last update timestamps."""

    state = request.app.state.orderbook_state
    symbols = state.get_active_symbols() or request.app.state.nse_fetcher.symbols
    return [SymbolStatus(symbol=symbol, last_update=state.get_last_update(symbol)) for symbol in symbols]
