"""FastAPI application entry point for the AlphaCore backend."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.detections import router as detections_router
from api.flow import router as flow_router
from api.health import router as health_router
from api.heatmap import router as heatmap_router
from api.narrative import router as narrative_router
from api.orderbook import router as orderbook_router
from api.signals import router as signals_router
from api.websocket import router as websocket_router
from config import get_settings
from data.nse_fetcher import DEFAULT_SYMBOLS, NSEFetcher
from data.orderbook_state import OrderBookStateManager, state_manager
from data.scheduler import DataScheduler
from database import connect, create_tables, disconnect, ensure_trade_signals_table

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown resources."""

    await connect()
    await create_tables()
    await ensure_trade_signals_table()

    fetcher = NSEFetcher(DEFAULT_SYMBOLS)
    state: OrderBookStateManager = state_manager
    history_limit = max(
        1,
        int(settings.ORDERBOOK_HISTORY_MINUTES * 60 / settings.NSE_FETCH_INTERVAL_SECONDS),
    )
    state.configure_history_limit(history_limit)
    scheduler = DataScheduler(fetcher, state)

    app.state.nse_fetcher = fetcher
    app.state.orderbook_state = state
    app.state.scheduler = scheduler

    scheduler.start()
    logger.info("AlphaCore backend started")
    try:
        yield
    finally:
        scheduler.stop()
        await disconnect()
        logger.info("AlphaCore backend stopped")


app = FastAPI(
    title="AlphaCore Order Book Engine API",
    description=(
        "Real-time NSE order book intelligence. "
        "Iceberg detection, spoofing detection, flow analysis."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(orderbook_router)
app.include_router(websocket_router)
app.include_router(detections_router)
app.include_router(flow_router)
app.include_router(heatmap_router)
app.include_router(narrative_router)
app.include_router(signals_router)
