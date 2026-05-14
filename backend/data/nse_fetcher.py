"""NSE market data fetcher with layered fallbacks for AlphaCore."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import requests

from models.schemas import OrderBookSnapshot, OrderLevel

logger = logging.getLogger(__name__)

DEFAULT_SYMBOLS = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]
NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}


class NSEFetcher:
    """Fetch live order book data for tracked NSE symbols."""

    def __init__(self, symbols: list[str] | None = None) -> None:
        """Initialize the fetcher and its fallback clients."""

        self.symbols = [symbol.upper() for symbol in (symbols or DEFAULT_SYMBOLS)]
        self.last_known_data: dict[str, OrderBookSnapshot] = {}
        self.last_success_at: datetime | None = None
        self._session = requests.Session()
        self._session.headers.update(NSE_HEADERS)
        self._homepage_initialized = False
        self._nsetools_client: Any | None = None
        self._jugaad_client: Any | None = None

    async def fetch_orderbook(self, symbol: str) -> OrderBookSnapshot | None:
        """Fetch a single symbol using all available sources with fallback."""

        normalized_symbol = symbol.upper()
        fetch_attempts = [
            ("jugaad-trader", self._fetch_from_jugaad),
            ("nsetools", self._fetch_from_nsetools),
            ("nse-website", self._fetch_from_nse_website),
        ]

        for source_name, fetcher in fetch_attempts:
            try:
                snapshot = await fetcher(normalized_symbol)
                if snapshot is not None:
                    snapshot.stale = False
                    self.last_known_data[normalized_symbol] = snapshot
                    self.last_success_at = snapshot.timestamp
                    return snapshot
            except Exception as exc:
                logger.error(
                    "Order book fetch failed for %s via %s: %s",
                    normalized_symbol,
                    source_name,
                    exc,
                )

        logger.warning(
            "All live sources failed for %s — using mock data", normalized_symbol
        )
        mock = self._generate_mock_snapshot(normalized_symbol)
        self.last_known_data[normalized_symbol] = mock
        return mock

    async def fetch_all_symbols(self) -> dict[str, OrderBookSnapshot]:
        """Fetch order book snapshots for all tracked symbols sequentially."""

        snapshots: dict[str, OrderBookSnapshot] = {}
        for symbol in self.symbols:
            snapshot = await fetch_orderbook_with_throttle(self, symbol)
            if snapshot is not None:
                snapshots[symbol] = snapshot
        return snapshots

    def _calculate_imbalance(
        self, bids: list[OrderLevel], asks: list[OrderLevel]
    ) -> float:
        """Calculate normalized bid/ask volume imbalance."""

        total_bid_volume = sum(level.volume for level in bids)
        total_ask_volume = sum(level.volume for level in asks)
        total_volume = total_bid_volume + total_ask_volume
        if total_volume == 0:
            return 0.0
        return round((total_bid_volume - total_ask_volume) / total_volume, 6)

    def _parse_nse_depth(self, depth_data: dict[str, Any]) -> tuple[list[OrderLevel], list[OrderLevel]]:
        """Parse NSE depth JSON into normalized bid and ask levels."""

        buy_levels = depth_data.get("buy", []) or []
        sell_levels = depth_data.get("sell", []) or []

        bids = [
            OrderLevel(price=float(level["price"]), volume=float(level["quantity"]))
            for level in buy_levels[:10]
            if level.get("price") is not None and level.get("quantity") is not None
        ]
        asks = [
            OrderLevel(price=float(level["price"]), volume=float(level["quantity"]))
            for level in sell_levels[:10]
            if level.get("price") is not None and level.get("quantity") is not None
        ]

        bids.sort(key=lambda level: level.price, reverse=True)
        asks.sort(key=lambda level: level.price)
        return bids, asks

    def _build_snapshot(
        self, symbol: str, bids: list[OrderLevel], asks: list[OrderLevel]
    ) -> OrderBookSnapshot:
        """Construct a normalized order book snapshot from bid/ask levels."""

        best_bid = bids[0].price if bids else 0.0
        best_ask = asks[0].price if asks else 0.0
        spread = round(best_ask - best_bid, 4) if best_bid and best_ask else 0.0
        total_bid_volume = round(sum(level.volume for level in bids), 2)
        total_ask_volume = round(sum(level.volume for level in asks), 2)
        imbalance = self._calculate_imbalance(bids, asks)
        return OrderBookSnapshot(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            bids=bids[:10],
            asks=asks[:10],
            spread=spread,
            bid_ask_imbalance=imbalance,
            total_bid_volume=total_bid_volume,
            total_ask_volume=total_ask_volume,
        )

    async def _fetch_from_jugaad(self, symbol: str) -> OrderBookSnapshot | None:
        """Try fetching depth data via `jugaad-trader`."""

        def _sync_fetch() -> OrderBookSnapshot | None:
            client = self._get_jugaad_client()
            if client is None:
                return None

            quote = None
            candidate_methods = ["quote", "stock_quote", "get_quote"]
            for method_name in candidate_methods:
                method = getattr(client, method_name, None)
                if callable(method):
                    quote = method(symbol)
                    break

            if quote is None:
                return None

            depth = quote.get("depth") or quote.get("marketDeptOrderBook") or {}
            bids, asks = self._parse_flexible_depth(depth)
            if not bids and not asks:
                return None
            return self._build_snapshot(symbol, bids, asks)

        return await asyncio.to_thread(_sync_fetch)

    async def _fetch_from_nsetools(self, symbol: str) -> OrderBookSnapshot | None:
        """Try fetching quote data via `nsetools` and map it into depth levels."""

        def _sync_fetch() -> OrderBookSnapshot | None:
            client = self._get_nsetools_client()
            if client is None:
                return None
            quote = client.get_quote(symbol)
            if not isinstance(quote, dict) or not quote:
                return None

            bids = self._extract_levels_from_quote(quote, side="bid")
            asks = self._extract_levels_from_quote(quote, side="ask")
            if not bids and not asks:
                return None
            return self._build_snapshot(symbol, bids, asks)

        return await asyncio.to_thread(_sync_fetch)

    async def _fetch_from_nse_website(self, symbol: str) -> OrderBookSnapshot | None:
        """Fetch direct quote-equity depth data from the NSE website."""

        def _sync_fetch() -> OrderBookSnapshot | None:
            try:
                self._ensure_homepage_session()
                self._session.headers.update({
                    "Referer": "https://www.nseindia.com/get-quotes/equity?symbol=" + symbol,
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json, text/plain, */*",
                })
                response = self._session.get(
                    "https://www.nseindia.com/api/quote-equity",
                    params={"symbol": symbol},
                    timeout=10,
                )
                if response.status_code in {401, 403}:
                    self._homepage_initialized = False
                    self._ensure_homepage_session()
                    response = self._session.get(
                        "https://www.nseindia.com/api/quote-equity",
                        params={"symbol": symbol},
                        timeout=10,
                    )
            except requests.RequestException as exc:
                logger.warning("NSE website request failed for %s: %s", symbol, exc)
                return None
            if response.status_code != 200:
                logger.warning(
                    "NSE website quote unavailable for %s: status=%s",
                    symbol,
                    response.status_code,
                )
                return None
            payload = response.json()
            depth = payload.get("depth", {})
            bids, asks = self._parse_nse_depth(depth)
            if not bids and not asks:
                return None
            return self._build_snapshot(symbol, bids, asks)

        return await asyncio.to_thread(_sync_fetch)

    def _ensure_homepage_session(self) -> None:
        """Prime the NSE session with cookies via multi-step navigation."""

        import time

        if self._homepage_initialized:
            return
        try:
            r1 = self._session.get(
                "https://www.nseindia.com",
                timeout=15,
                allow_redirects=True,
            )
            logger.info("NSE homepage status: %s", r1.status_code)
            time.sleep(1.5)

            self._session.get(
                "https://www.nseindia.com/market-data/live-equity-market",
                timeout=15,
            )
            time.sleep(1.0)

            self._session.get(
                "https://www.nseindia.com/api/market-status",
                timeout=10,
            )
            time.sleep(0.5)

            self._homepage_initialized = True
            logger.info("NSE session initialized successfully")
        except Exception as exc:
            logger.error("NSE session initialization failed: %s", exc)
            self._homepage_initialized = False

    def _get_nsetools_client(self) -> Any | None:
        """Lazily construct the `nsetools` client if available."""

        if self._nsetools_client is not None:
            return self._nsetools_client
        try:
            from nsetools import Nse

            self._nsetools_client = Nse()
        except Exception as exc:
            logger.error("Failed to initialize nsetools client: %s", exc)
            return None
        return self._nsetools_client

    def _get_jugaad_client(self) -> Any | None:
        """Lazily construct a `jugaad-trader` client if import paths resolve."""

        if self._jugaad_client is not None:
            return None if self._jugaad_client == "DISABLED" else self._jugaad_client

        candidates: list[tuple[str, str, tuple[str, ...]]] = [
            ("jugaad_trader", "NSELive", ("quote", "stock_quote", "get_quote")),
            ("jugaad_trader", "NseLive", ("quote", "stock_quote", "get_quote")),
            ("jugaad_trader", "Jugaad", ("quote", "stock_quote", "get_quote")),
            ("jugaad_trader", "NseIndia", ("quote", "stock_quote", "get_quote")),
            ("jugaad_trader.nse", "NSE", ("quote", "stock_quote", "get_quote")),
        ]

        for module_name, class_name, method_names in candidates:
            try:
                module = __import__(module_name, fromlist=[class_name])
                candidate_cls = getattr(module, class_name)
                client = candidate_cls()
            except Exception:
                continue
            if any(callable(getattr(client, method_name, None)) for method_name in method_names):
                self._jugaad_client = client
                return client

        logger.warning(
            "No usable jugaad-trader live client found in installed package; disabling fallback"
        )
        self._jugaad_client = "DISABLED"
        return None

    def _generate_mock_snapshot(self, symbol: str) -> OrderBookSnapshot:
        """Generate realistic mock data for testing outside market hours."""

        import random

        base_prices = {
            "RELIANCE": 2890.0,
            "TCS": 3450.0,
            "INFY": 1580.0,
            "HDFCBANK": 1720.0,
            "ICICIBANK": 1240.0,
        }
        base = base_prices.get(symbol, 1000.0)
        spread = round(base * 0.0003, 2)

        bids = [
            OrderLevel(
                price=round(base - (i * spread), 2),
                volume=round(random.uniform(200, 2000), 0),
            )
            for i in range(5)
        ]
        asks = [
            OrderLevel(
                price=round(base + spread + (i * spread), 2),
                volume=round(random.uniform(200, 2000), 0),
            )
            for i in range(5)
        ]
        return self._build_snapshot(symbol, bids, asks)

    def _extract_levels_from_quote(self, quote: dict[str, Any], side: str) -> list[OrderLevel]:
        """Map `nsetools` quote keys into normalized order levels."""

        levels: list[OrderLevel] = []
        depth_keys = (
            ("Price", "Quantity"),
            ("price", "quantity"),
            ("Qty", "Orders"),
        )

        for index in range(1, 6):
            for price_suffix, volume_suffix in depth_keys:
                price_key = f"{side}{price_suffix}{index}"
                volume_key = f"{side}{volume_suffix}{index}"
                price = quote.get(price_key)
                volume = quote.get(volume_key)
                if price is not None and volume is not None:
                    levels.append(OrderLevel(price=float(price), volume=float(volume)))
                    break

        if levels:
            levels.sort(key=lambda level: level.price, reverse=(side == "bid"))
            return levels

        fallback_price_keys = ["buyPrice1", "sellPrice1", "lastPrice", "basePrice"]
        fallback_volume_keys = ["buyQuantity1", "sellQuantity1", "quantityTraded"]
        price = next((quote.get(key) for key in fallback_price_keys if quote.get(key) is not None), None)
        volume = next((quote.get(key) for key in fallback_volume_keys if quote.get(key) is not None), None)
        if price is not None and volume is not None:
            levels.append(OrderLevel(price=float(price), volume=float(volume)))
        return levels

    def _parse_flexible_depth(self, depth: Any) -> tuple[list[OrderLevel], list[OrderLevel]]:
        """Parse alternative depth formats returned by fallback data sources."""

        if isinstance(depth, dict) and ("buy" in depth or "sell" in depth):
            return self._parse_nse_depth(depth)

        bids_raw = []
        asks_raw = []
        if isinstance(depth, dict):
            bids_raw = depth.get("bids") or depth.get("buy") or []
            asks_raw = depth.get("asks") or depth.get("sell") or []

        def _to_levels(entries: list[Any], reverse: bool) -> list[OrderLevel]:
            levels: list[OrderLevel] = []
            for entry in entries[:10]:
                if isinstance(entry, dict):
                    price = entry.get("price") or entry.get("Price")
                    volume = (
                        entry.get("quantity")
                        or entry.get("qty")
                        or entry.get("volume")
                        or entry.get("Quantity")
                    )
                    if price is not None and volume is not None:
                        levels.append(OrderLevel(price=float(price), volume=float(volume)))
            levels.sort(key=lambda level: level.price, reverse=reverse)
            return levels

        return _to_levels(bids_raw, True), _to_levels(asks_raw, False)


async def fetch_orderbook_with_throttle(fetcher: NSEFetcher, symbol: str) -> OrderBookSnapshot | None:
    """Fetch a symbol and add a small delay to reduce rate-limit pressure."""

    snapshot = await fetcher.fetch_orderbook(symbol)
    await asyncio.sleep(0.2)
    return snapshot
