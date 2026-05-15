"""Periodic data scheduler for refreshing AlphaCore market state."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import get_settings
from data.nse_fetcher import NSEFetcher
from data.orderbook_state import OrderBookStateManager
from database import get_database, order_book_snapshots, serialize_levels, trade_signals
from engines.alpha_engine import alpha_engine
from engines.circuit_breaker import circuit_breaker
from engines.kill_switch import kill_switch
from engines.liquidity_score import LiquidityScorer
from engines.otr_monitor import otr_monitor
from engines.spread_tracker import SpreadTracker
from engines.vwap import VWAPEngine
from ha.journal import journal
from metrics import ACTIVE_SIGNALS, ORDER_BOOK_UPDATES
from models.schemas import OrderBookSnapshot

logger = logging.getLogger(__name__)

vwap_engine = VWAPEngine()
spread_tracker = SpreadTracker()
liquidity_scorer = LiquidityScorer()


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
            if kill_switch.is_active:
                logger.warning("Kill switch active — cycle skipped")
                return

            snapshots = await self.fetcher.fetch_all_symbols()
            updated = 0
            for symbol, snapshot in snapshots.items():
                levels_count = len(snapshot.bids) + len(snapshot.asks)
                for _ in range(levels_count):
                    otr_monitor.record_order(symbol)

                current_price = self._mid_price(snapshot)
                previous_snapshot = self.state.get_latest(symbol)
                previous_price = self._mid_price(previous_snapshot) if previous_snapshot is not None else 0.0
                if circuit_breaker.check(symbol, current_price, previous_price):
                    logger.warning("Skipping signal generation for %s due to circuit breaker halt", symbol.upper())
                    await journal.write(
                        "circuit_break",
                        symbol.upper(),
                        {
                            "current_price": current_price,
                            "previous_price": previous_price,
                            "status": circuit_breaker.status().get(symbol.upper(), {}),
                        },
                    )
                    await self.state.update(symbol, snapshot)
                    ORDER_BOOK_UPDATES.labels(symbol=symbol.upper()).inc()
                    await self._store_snapshot(snapshot)
                    updated += 1
                    continue

                await self.state.update(symbol, snapshot)
                ORDER_BOOK_UPDATES.labels(symbol=symbol.upper()).inc()
                await self._store_snapshot(snapshot)
                await self._update_microstructure(symbol, snapshot)
                await self._generate_and_store_signal(symbol)
                updated += 1

            failed = len(self.fetcher.symbols) - updated
            logger.info("NSE fetch cycle complete: updated=%s failed=%s", updated, failed)
        except Exception as exc:
            logger.error("Scheduled NSE fetch job failed: %s", exc)

    async def _update_microstructure(self, symbol: str, snapshot: OrderBookSnapshot) -> None:
        best_bid = float(snapshot.bids[0].price) if snapshot.bids else 0.0
        best_ask = float(snapshot.asks[0].price) if snapshot.asks else 0.0
        last_price = self._mid_price(snapshot)
        total_depth = float(snapshot.total_bid_volume or 0.0) + float(snapshot.total_ask_volume or 0.0)
        spread_tracker.update(symbol, best_bid, best_ask)
        await vwap_engine.update(
            symbol=symbol,
            price=last_price if last_price > 0 else best_bid or best_ask or 0.0,
            volume=1.0,
            ts=snapshot.timestamp if snapshot.timestamp else datetime.now(timezone.utc),
        )
        spread_bps = spread_tracker.get_spread(symbol).get("relative", 0.0)
        otr = otr_monitor.get_otr(symbol) if symbol else 0.0
        one_min_window = vwap_engine._windows.get(symbol.upper(), {}).get("1min", [])
        price_history = [float(p) for _ts, p, _v in one_min_window]
        liquidity_scorer.update(
            symbol=symbol,
            spread_bps=float(spread_bps or 0.0),
            depth=total_depth,
            otr=float(otr or 0.0),
            price_history=price_history,
        )
        bids = [(float(level.price), float(level.volume)) for level in snapshot.bids[:5]]
        asks = [(float(level.price), float(level.volume)) for level in snapshot.asks[:5]]
        alpha_engine.update(
            symbol=symbol,
            price=last_price if last_price > 0 else best_bid or best_ask or 0.0,
            ts=snapshot.timestamp if snapshot.timestamp else datetime.now(timezone.utc),
            bids=bids,
            asks=asks,
        )

    @staticmethod
    def _mid_price(snapshot: OrderBookSnapshot | None) -> float:
        if snapshot is None:
            return 0.0
        best_bid = float(snapshot.bids[0].price) if snapshot.bids else None
        best_ask = float(snapshot.asks[0].price) if snapshot.asks else None
        if best_bid is not None and best_ask is not None:
            return (best_bid + best_ask) / 2.0
        if best_bid is not None:
            return best_bid
        if best_ask is not None:
            return best_ask
        return 0.0

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
                ACTIVE_SIGNALS.labels(symbol=symbol.upper()).set(0)
                return
            if otr_monitor.is_breached(symbol):
                logger.warning("High OTR breach for %s: %.2f", symbol.upper(), otr_monitor.get_otr(symbol))
                if "High OTR" not in signal["reasons"]:
                    signal["reasons"].append("High OTR")
            await journal.write("signal", signal["symbol"], signal)

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
            ACTIVE_SIGNALS.labels(symbol=signal["symbol"]).set(1)
        except Exception as exc:
            logger.error("Failed to generate/store signal for %s: %s", symbol, exc)
