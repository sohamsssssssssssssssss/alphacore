"""NarrativeEdge signal intake and retrieval endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException

from database import get_database, narrative_signals
from models.schemas import NarrativeSignalInput, NarrativeSignalResponse

router = APIRouter(prefix="/api/narrative", tags=["narrative"])


@router.post("/signal", response_model=NarrativeSignalResponse)
async def ingest_narrative_signal(payload: NarrativeSignalInput) -> NarrativeSignalResponse:
    """Insert a NarrativeEdge signal into PostgreSQL and return it."""

    received_at = datetime.now(timezone.utc)
    started_value = payload.started or None
    try:
        started_date = datetime.fromisoformat(started_value).date() if started_value else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid `started` date format") from exc
    insert_query = narrative_signals.insert().values(
        received_at=received_at,
        narrative=payload.narrative,
        confidence=payload.confidence,
        strength=payload.strength,
        regime=payload.regime,
        started=started_date,
    )
    inserted_id = await get_database().execute(insert_query)
    return NarrativeSignalResponse(
        id=int(inserted_id),
        received_at=received_at,
        narrative=payload.narrative,
        confidence=payload.confidence,
        strength=payload.strength,
        regime=payload.regime,
        started=started_value,
    )


@router.get("/current", response_model=NarrativeSignalResponse)
async def get_current_narrative_signal() -> NarrativeSignalResponse:
    """Return the most recent stored NarrativeEdge signal."""

    query = sa.select(narrative_signals).order_by(narrative_signals.c.received_at.desc()).limit(1)
    row = await get_database().fetch_one(query)
    if row is None:
        raise HTTPException(status_code=404, detail="No narrative signals available")
    started = row["started"].isoformat() if row["started"] is not None else None
    return NarrativeSignalResponse(
        id=row["id"],
        received_at=row["received_at"],
        narrative=row["narrative"],
        confidence=row["confidence"],
        strength=row["strength"],
        regime=row["regime"],
        started=started,
    )
