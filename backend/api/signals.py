"""Trade signal endpoints."""

from __future__ import annotations

import json

import sqlalchemy as sa
from fastapi import APIRouter

from database import get_database, trade_signals
from models.schemas import TradeSignal

router = APIRouter(prefix="/api/signals", tags=["signals"])


def _normalize_reasons(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            return [value]
    return []


@router.get("/latest", response_model=dict[str, TradeSignal])
async def get_latest_signals() -> dict[str, dict]:
    """Return latest signal per symbol."""

    rows = await get_database().fetch_all(
        sa.text(
            """
            SELECT DISTINCT ON (symbol)
                id, symbol, direction, entry_price, stop_loss, target_price,
                confidence, score, reasons, generated_at
            FROM trade_signals
            ORDER BY symbol, generated_at DESC, id DESC
            """
        )
    )

    return {
        row["symbol"]: {
            "id": row["id"],
            "symbol": row["symbol"],
            "direction": row["direction"],
            "entry_price": float(row["entry_price"]),
            "stop_loss": float(row["stop_loss"]),
            "target_price": float(row["target_price"]),
            "confidence": int(row["confidence"]),
            "score": int(row["score"]),
            "reasons": _normalize_reasons(row["reasons"]),
            "generated_at": row["generated_at"].isoformat(),
        }
        for row in rows
    }


@router.get("/{symbol}", response_model=list[TradeSignal])
async def get_signals_for_symbol(symbol: str) -> list[dict]:
    """Return most recent 20 signals for one symbol."""

    rows = await get_database().fetch_all(
        sa.select(trade_signals)
        .where(trade_signals.c.symbol == symbol.upper())
        .order_by(trade_signals.c.generated_at.desc(), trade_signals.c.id.desc())
        .limit(20)
    )

    return [
        {
            "id": row["id"],
            "symbol": row["symbol"],
            "direction": row["direction"],
            "entry_price": float(row["entry_price"]),
            "stop_loss": float(row["stop_loss"]),
            "target_price": float(row["target_price"]),
            "confidence": int(row["confidence"]),
            "score": int(row["score"]),
            "reasons": _normalize_reasons(row["reasons"]),
            "generated_at": row["generated_at"].isoformat(),
        }
        for row in rows
    ]
