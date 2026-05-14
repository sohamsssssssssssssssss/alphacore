"""WebSocket endpoints for real-time AlphaCore order book updates."""

from __future__ import annotations

import contextlib
import logging
import asyncio
from datetime import datetime, timezone

import sqlalchemy as sa
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from database import get_database, iceberg_detections, spoof_detections, trade_signals
from ws.binary_protocol import (
    DETECTION_EVENT,
    HEARTBEAT,
    ORDER_BOOK_SNAPSHOT,
    TRADE_SIGNAL,
    BinaryProtocol,
    BinaryProtocolError,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


@router.websocket("/ws/orderbook/{symbol}")
async def orderbook_websocket(websocket: WebSocket, symbol: str) -> None:
    """Stream real-time order book updates for a symbol to a client."""

    await websocket.accept()
    state = websocket.app.state.orderbook_state
    normalized_symbol = symbol.upper()
    state.add_websocket(websocket, normalized_symbol)

    try:
        current_snapshot = state.get_latest(normalized_symbol)
        if current_snapshot is not None:
            await websocket.send_json(
                {
                    "type": "orderbook_update",
                    "symbol": current_snapshot.symbol,
                    "timestamp": current_snapshot.timestamp.isoformat(),
                    "bids": [level.model_dump() for level in current_snapshot.bids],
                    "asks": [level.model_dump() for level in current_snapshot.asks],
                    "spread": current_snapshot.spread,
                    "bid_ask_imbalance": current_snapshot.bid_ask_imbalance,
                    "total_bid_volume": current_snapshot.total_bid_volume,
                    "total_ask_volume": current_snapshot.total_ask_volume,
                }
            )

        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected for %s", normalized_symbol)
    except Exception as exc:
        logger.error("WebSocket error for %s: %s", normalized_symbol, exc)
    finally:
        state.remove_websocket(websocket)
        with contextlib.suppress(Exception):
            await websocket.close()


@router.websocket("/ws/binary")
async def binary_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    heartbeat_task = None

    async def send_heartbeat() -> None:
        while True:
            await websocket.send_bytes(BinaryProtocol.heartbeat())
            await asyncio.sleep(5)

    heartbeat_task = asyncio.create_task(send_heartbeat())
    try:
        while True:
            raw = await websocket.receive_bytes()
            msg_type, payload = BinaryProtocol.decode(raw)
            if msg_type == ORDER_BOOK_SNAPSHOT:
                symbol = str(payload.get("symbol", "RELIANCE")).upper()
                snapshot = websocket.app.state.orderbook_state.get_latest(symbol)
                response = {
                    "symbol": symbol,
                    "snapshot": snapshot.model_dump(mode="json") if snapshot is not None else None,
                }
                await websocket.send_bytes(BinaryProtocol.encode(ORDER_BOOK_SNAPSHOT, response))
            elif msg_type == TRADE_SIGNAL:
                rows = await get_database().fetch_all(
                    sa.text(
                        """
                        SELECT id, symbol, direction, entry_price, stop_loss, target_price, confidence, score, reasons, generated_at
                        FROM trade_signals
                        ORDER BY generated_at DESC, id DESC
                        LIMIT 5
                        """
                    )
                )
                await websocket.send_bytes(
                    BinaryProtocol.encode(
                        TRADE_SIGNAL,
                        {
                            "signals": [
                                {
                                    "id": row["id"],
                                    "symbol": row["symbol"],
                                    "direction": row["direction"],
                                    "entry_price": float(row["entry_price"]),
                                    "stop_loss": float(row["stop_loss"]),
                                    "target_price": float(row["target_price"]),
                                    "confidence": int(row["confidence"]),
                                    "score": int(row["score"]),
                                    "reasons": row["reasons"],
                                    "generated_at": row["generated_at"].isoformat(),
                                }
                                for row in rows
                            ]
                        },
                    )
                )
            elif msg_type == DETECTION_EVENT:
                iceberg_rows = await get_database().fetch_all(
                    sa.select(iceberg_detections)
                    .order_by(iceberg_detections.c.detected_at.desc(), iceberg_detections.c.id.desc())
                    .limit(5)
                )
                spoof_rows = await get_database().fetch_all(
                    sa.select(spoof_detections)
                    .order_by(spoof_detections.c.detected_at.desc(), spoof_detections.c.id.desc())
                    .limit(5)
                )
                await websocket.send_bytes(
                    BinaryProtocol.encode(
                        DETECTION_EVENT,
                        {
                            "icebergs": [dict(row) for row in iceberg_rows],
                            "spoofs": [dict(row) for row in spoof_rows],
                        },
                    )
                )
            elif msg_type == HEARTBEAT:
                await websocket.send_bytes(
                    BinaryProtocol.encode(HEARTBEAT, {"echo": True, "ts": datetime.now(timezone.utc).isoformat()})
                )
            else:
                await websocket.send_bytes(BinaryProtocol.encode(HEARTBEAT, {"warning": "unsupported_message_type"}))
    except BinaryProtocolError as exc:
        logger.warning("Binary WS protocol error: %s", exc)
    except WebSocketDisconnect:
        logger.info("Binary WS client disconnected")
    except Exception as exc:
        logger.error("Binary WS error: %s", exc)
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            with contextlib.suppress(Exception):
                await heartbeat_task
        with contextlib.suppress(Exception):
            await websocket.close()
