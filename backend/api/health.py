"""Health endpoints for the AlphaCore backend."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request

from database import ping_database
from models.schemas import HealthResponse

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def get_health(request: Request) -> HealthResponse:
    """Return application health information."""

    state = request.app.state.orderbook_state
    fetcher = request.app.state.nse_fetcher
    db_connected = await ping_database()
    last_data_fetch = state.get_last_fetch_time() or fetcher.last_success_at
    nse_connected = last_data_fetch is not None
    status = "ok" if db_connected else "degraded"
    return HealthResponse(
        status=status,
        timestamp=datetime.now(timezone.utc),
        nse_connected=nse_connected,
        active_symbols=state.get_active_symbols() or fetcher.symbols,
        last_data_fetch=last_data_fetch,
        db_connected=db_connected,
    )
