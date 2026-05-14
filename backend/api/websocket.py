"""WebSocket endpoints for real-time AlphaCore order book updates."""

from __future__ import annotations

import contextlib
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

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
