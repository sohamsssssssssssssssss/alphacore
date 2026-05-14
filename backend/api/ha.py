"""High-availability introspection endpoints."""

from __future__ import annotations

import sqlalchemy as sa
from fastapi import APIRouter, Query, Request

from database import get_database
from ha.journal import journal

router = APIRouter(prefix="/api/ha", tags=["ha"])


@router.get("/status")
async def get_ha_status(request: Request) -> dict:
    entries = journal.read_since()
    database = get_database()
    last_iceberg_seq = await database.fetch_val(sa.text("SELECT COALESCE(MAX(seq_num), 0) FROM iceberg_detections"))
    last_spoof_seq = await database.fetch_val(sa.text("SELECT COALESCE(MAX(seq_num), 0) FROM spoof_detections"))
    last_signal_seq = await database.fetch_val(sa.text("SELECT COALESCE(MAX(seq_num), 0) FROM trade_signals"))

    return {
        "journal_events": len(entries),
        "last_event_at": entries[-1]["ts"] if entries else None,
        "recovery_summary": getattr(request.app.state, "recovery_summary", {}),
        "sequence_numbers": {
            "last_iceberg_seq": int(last_iceberg_seq or 0),
            "last_spoof_seq": int(last_spoof_seq or 0),
            "last_signal_seq": int(last_signal_seq or 0),
        },
    }


@router.get("/journal")
async def get_ha_journal(limit: int = Query(default=50, ge=1, le=200)) -> list[dict]:
    entries = journal.read_since()
    return entries[-limit:]
