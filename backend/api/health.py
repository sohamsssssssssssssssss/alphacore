"""Health endpoints for the AlphaCore backend."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request

from database import ping_database
from engines.circuit_breaker import circuit_breaker
from engines.kill_switch import kill_switch
from ha.journal import journal
from models.schemas import HealthResponse

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def get_health(request: Request) -> HealthResponse:
    """Return application health information."""

    db_connected = await ping_database()
    scheduler = request.app.state.scheduler
    started_at = getattr(request.app.state, "started_at", datetime.now(timezone.utc))
    uptime_seconds = max(0, int((datetime.now(timezone.utc) - started_at).total_seconds()))
    entries = journal.read_since()

    return HealthResponse(
        status="healthy" if db_connected else "degraded",
        database="connected" if db_connected else "disconnected",
        scheduler="running" if scheduler.scheduler.running else "stopped",
        kill_switch=kill_switch.is_active,
        circuit_breakers_active=len(circuit_breaker.status()),
        journal_events=len(entries),
        last_journal_event=entries[-1]["ts"] if entries else None,
        uptime_seconds=uptime_seconds,
    )
