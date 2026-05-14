"""Detection endpoints for iceberg, spoofing, and summary analytics."""

from __future__ import annotations

from datetime import datetime, time, timezone

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Query, Request

from api.rate_limit import limiter
from database import get_database, iceberg_detections, spoof_detections
from engines.flow_engine import flow_engine
from engines.iceberg_detector import iceberg_detector
from engines.spoof_detector import spoof_detector
from models.schemas import DetectionSummary, IcebergDetection, SpoofDetection

router = APIRouter(prefix="/api/detections", tags=["detections"])


def _row_to_iceberg_detection(row: sa.Row | sa.RowMapping) -> IcebergDetection:
    """Convert an iceberg detection database row into the API schema."""

    return IcebergDetection(
        id=row["id"],
        symbol=row["symbol"],
        detected_at=row["detected_at"],
        price_level=float(row["price_level"]),
        visible_size=float(row["visible_size"]),
        estimated_hidden_volume=float(row["estimated_hidden_volume"]),
        refill_count=row["refill_count"],
        direction=row["direction"],
        confidence_score=row["confidence_score"],
        is_active=row["is_active"],
        last_seen_at=row["last_seen_at"],
    )


def _row_to_spoof_detection(row: sa.Row | sa.RowMapping) -> SpoofDetection:
    """Convert a spoof detection database row into the API schema."""

    return SpoofDetection(
        id=row["id"],
        symbol=row["symbol"],
        detected_at=row["detected_at"],
        order_price=float(row["order_price"]),
        order_size=float(row["order_size"]),
        spoof_score=row["spoof_score"],
        severity=row["severity"],
        time_active_seconds=row["time_active_seconds"],
        price_impact=float(row["price_impact"]) if row["price_impact"] is not None else None,
        counter_trade_detected=row["counter_trade_detected"],
        check_refill_score=row["check_refill_score"],
        check_cancel_speed_score=row["check_cancel_speed_score"],
        check_fill_ratio_score=row["check_fill_ratio_score"],
        check_price_impact_score=row["check_price_impact_score"],
        check_counter_trade_score=row["check_counter_trade_score"],
    )


@router.get("/icebergs", response_model=list[IcebergDetection])
@limiter.limit("100/minute")
async def get_icebergs(
    request: Request,
    symbol: str | None = None,
    active_only: bool = Query(default=True),
) -> list[IcebergDetection]:
    """Return current iceberg detections, optionally filtered by symbol."""

    query = sa.select(iceberg_detections).order_by(
        iceberg_detections.c.detected_at.desc(),
        iceberg_detections.c.id.desc(),
    )
    if symbol:
        query = query.where(iceberg_detections.c.symbol == symbol.upper())
    if active_only:
        query = query.where(iceberg_detections.c.is_active.is_(True))
    query = query.limit(100)

    rows = await get_database().fetch_all(query)
    return [_row_to_iceberg_detection(row) for row in rows]


@router.get("/icebergs/{symbol}", response_model=list[IcebergDetection])
async def get_icebergs_for_symbol(symbol: str) -> list[IcebergDetection]:
    """Return iceberg detections for a single symbol."""

    rows = await get_database().fetch_all(
        sa.select(iceberg_detections)
        .where(iceberg_detections.c.symbol == symbol.upper())
        .order_by(
            iceberg_detections.c.detected_at.desc(),
            iceberg_detections.c.id.desc(),
        )
    )
    detections = [_row_to_iceberg_detection(row) for row in rows]
    if not detections:
        raise HTTPException(status_code=404, detail=f"No iceberg detections found for {symbol.upper()}")
    return detections


@router.get("/spoof", response_model=list[SpoofDetection])
@limiter.limit("100/minute")
async def get_spoof_alerts(
    request: Request,
    symbol: str | None = None,
    min_severity: str = Query(default="LOW"),
) -> list[SpoofDetection]:
    """Return spoof alerts filtered by symbol and minimum severity."""

    severity_rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
    threshold = severity_rank.get(min_severity.upper(), 1)
    query = sa.select(spoof_detections).order_by(
        spoof_detections.c.detected_at.desc(),
        spoof_detections.c.id.desc(),
    )
    if symbol:
        query = query.where(spoof_detections.c.symbol == symbol.upper())
    query = query.limit(100)
    rows = await get_database().fetch_all(query)
    alerts = [_row_to_spoof_detection(row) for row in rows]
    return [alert for alert in alerts if severity_rank.get(alert.severity, 1) >= threshold]


@router.get("/spoof/{symbol}", response_model=list[SpoofDetection])
async def get_spoof_alerts_for_symbol(symbol: str) -> list[SpoofDetection]:
    """Return spoof alerts for a single symbol."""

    rows = await get_database().fetch_all(
        sa.select(spoof_detections)
        .where(spoof_detections.c.symbol == symbol.upper())
        .order_by(
            spoof_detections.c.detected_at.desc(),
            spoof_detections.c.id.desc(),
        )
    )
    alerts = [_row_to_spoof_detection(row) for row in rows]
    if not alerts:
        raise HTTPException(status_code=404, detail=f"No spoof alerts found for {symbol.upper()}")
    return alerts


@router.get("/summary", response_model=DetectionSummary)
async def get_detection_summary(request: Request) -> DetectionSummary:
    """Return a high-level summary of detections and current flow."""

    today = datetime.now(timezone.utc).date()
    start_of_day = datetime.combine(today, time.min, tzinfo=timezone.utc)
    database = get_database()
    total_icebergs = await database.fetch_val(
        sa.select(sa.func.count())
        .select_from(iceberg_detections)
        .where(iceberg_detections.c.detected_at >= start_of_day)
    )
    total_spoof_alerts_today = await database.fetch_val(
        sa.select(sa.func.count())
        .select_from(spoof_detections)
        .where(spoof_detections.c.detected_at >= start_of_day)
    )
    high_severity_spoof_count = await database.fetch_val(
        sa.select(sa.func.count())
        .select_from(spoof_detections)
        .where(
            spoof_detections.c.detected_at >= start_of_day,
            spoof_detections.c.severity == "HIGH",
        )
    )
    medium_severity_spoof_count = await database.fetch_val(
        sa.select(sa.func.count())
        .select_from(spoof_detections)
        .where(
            spoof_detections.c.detected_at >= start_of_day,
            spoof_detections.c.severity == "MEDIUM",
        )
    )
    low_severity_spoof_count = await database.fetch_val(
        sa.select(sa.func.count())
        .select_from(spoof_detections)
        .where(
            spoof_detections.c.detected_at >= start_of_day,
            spoof_detections.c.severity == "LOW",
        )
    )
    iceberg_symbols = await database.fetch_all(
        sa.select(sa.distinct(iceberg_detections.c.symbol))
        .where(iceberg_detections.c.detected_at >= start_of_day)
        .order_by(iceberg_detections.c.symbol.asc())
    )
    spoof_symbols = await database.fetch_all(
        sa.select(sa.distinct(spoof_detections.c.symbol))
        .where(spoof_detections.c.detected_at >= start_of_day)
        .order_by(spoof_detections.c.symbol.asc())
    )

    del request
    return DetectionSummary(
        total_icebergs=int(total_icebergs or 0),
        total_spoof=int(total_spoof_alerts_today or 0),
        high_severity_spoof=int(high_severity_spoof_count or 0),
        medium_severity_spoof=int(medium_severity_spoof_count or 0),
        low_severity_spoof=int(low_severity_spoof_count or 0),
        symbols_with_icebergs=[row[0] for row in iceberg_symbols],
        symbols_with_spoof=[row[0] for row in spoof_symbols],
    )
