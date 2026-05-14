"""Periodic data scheduler for refreshing AlphaCore market state."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import get_settings
from data.nse_fetcher import NSEFetcher
from data.orderbook_state import OrderBookStateManager
from database import get_database, order_book_snapshots, serialize_levels, trade_signals
from engines.alpha_engine import alpha_engine
from models.schemas import OrderBookSnapshot

logger = logging.getLogger(__name__)


class DataScheduler:
    """Manage periodic background fetching of NSE order book data."""

    def __init__(self, fetcher: NSEFetcher, state: OrderBookStateManager) -> None:
        """Initialize the scheduler with its data dependencies."""

        self.fetcher = fetcher
        self.state = state
        self.settings = get_settings()
        self.scheduler = AsyncIOScheduler()

    def start(self) -> None:
        """Start periodic fetches and trigger the first job immediately."""

        self.scheduler.add_job(
            self._fetch_job,
            "interval",
            seconds=self.settings.NSE_FETCH_INTERVAL_SECONDS,
            max_instances=1,
            coalesce=True,
        )
        self.scheduler.start()
        self.scheduler.add_job(self._fetch_job, trigger="date")

    def stop(self) -> None:
        """Stop the scheduler without raising if already stopped."""

        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    async def _fetch_job(self) -> None:
        """Fetch all tracked symbols and update the shared state manager."""

        try:
            snapshots = await self.fetcher.fetch_all_symbols()
            updated = 0
            for symbol, snapshot in snapshots.items():
                await self.state.update(symbol, snapshot)
                await self._store_snapshot(snapshot)
                await self._generate_and_store_signal(symbol)
                updated += 1

            failed = len(self.fetcher.symbols) - updated
            logger.info("NSE fetch cycle complete: updated=%s failed=%s", updated, failed)
        except Exception as exc:
            logger.error("Scheduled NSE fetch job failed: %s", exc)

    async def _store_snapshot(self, snapshot: OrderBookSnapshot) -> None:
        """Persist a snapshot to PostgreSQL."""

        try:
            await get_database().execute(
                order_book_snapshots.insert().values(
                    symbol=snapshot.symbol,
                    timestamp=snapshot.timestamp,
                    bids=serialize_levels(snapshot.bids),
                    asks=serialize_levels(snapshot.asks),
                    spread=snapshot.spread,
                    bid_ask_imbalance=snapshot.bid_ask_imbalance,
                    total_bid_volume=snapshot.total_bid_volume,
                    total_ask_volume=snapshot.total_ask_volume,
                )
            )
        except Exception as exc:
            logger.error("Failed to persist snapshot for %s: %s", snapshot.symbol, exc)

    async def _generate_and_store_signal(self, symbol: str) -> None:
        """Generate and persist alpha signal for a symbol if directional edge exists."""

        try:
            signal = await alpha_engine.generate_signal(symbol)
            if signal is None:
                return

            await get_database().execute(
                trade_signals.insert().values(
                    symbol=signal["symbol"],
                    direction=signal["direction"],
                    entry_price=signal["entry_price"],
                    stop_loss=signal["stop_loss"],
                    target_price=signal["target_price"],
                    confidence=signal["confidence"],
                    score=signal["score"],
                    reasons=signal["reasons"],
                    generated_at=signal["generated_at"],
                )
            )
            logger.info(
                "Signal: symbol=%s direction=%s confidence=%s entry=%s",
                signal["symbol"],
                signal["direction"],
                signal["confidence"],
                signal["entry_price"],
            )
        except Exception as exc:
            logger.error("Failed to generate/store signal for %s: %s", symbol, exc)
