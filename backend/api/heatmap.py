"""Heatmap endpoints for AlphaCore liquidity visualization."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Query

from database import get_database, heatmap_matrix
from models.schemas import HeatmapMatrixResponse

router = APIRouter(prefix="/api/heatmap", tags=["heatmap"])


@router.get("/{symbol}", response_model=HeatmapMatrixResponse)
async def get_heatmap(
    symbol: str,
    window_minutes: int = Query(default=30, ge=1, le=60),
) -> HeatmapMatrixResponse:
    """Return heatmap data for a symbol in the requested time window."""

    normalized_symbol = symbol.upper()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    rows = await get_database().fetch_all(
        sa.select(heatmap_matrix)
        .where(
            heatmap_matrix.c.symbol == normalized_symbol,
            heatmap_matrix.c.snapshot_at >= cutoff,
        )
        .order_by(
            heatmap_matrix.c.snapshot_at.asc(),
            heatmap_matrix.c.price_level.desc(),
        )
    )

    if not rows:
        raise HTTPException(status_code=404, detail=f"No heatmap data available for {symbol.upper()}")

    timestamps = sorted({row["snapshot_at"] for row in rows})
    price_levels = sorted(
        {float(row["price_level"]) for row in rows},
        reverse=True,
    )
    volume_lookup = {
        (float(row["price_level"]), row["snapshot_at"]): float(row["total_volume"])
        for row in rows
    }
    matrix = [
        [volume_lookup.get((price_level, timestamp), 0.0) for timestamp in timestamps]
        for price_level in price_levels
    ]
    max_volume = max((max(row) for row in matrix), default=0.0)

    return HeatmapMatrixResponse(
        symbol=normalized_symbol,
        matrix=matrix,
        price_levels=[f"{price_level:.2f}" for price_level in price_levels],
        time_labels=[timestamp.strftime("%H:%M:%S") for timestamp in timestamps],
        max_volume=max_volume,
    )
