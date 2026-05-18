from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable

logger = logging.getLogger(__name__)

try:
    from SmartApi import SmartConnect
    from SmartApi.smartWebSocketV2 import SmartWebSocketV2
    ANGEL_AVAILABLE = True
except ImportError:
    ANGEL_AVAILABLE = False
    logger.warning("angel-one smartapi not installed. Run: pip3.11 install smartapi-python")


# NSE token map — maps symbol name to Angel One token ID
# Add more symbols as needed from Angel One's instrument list
NSE_TOKEN_MAP: dict[str, str] = {
    "RELIANCE":  "2885",
    "TCS":       "11536",
    "INFY":      "1594",
    "HDFCBANK":  "1333",
    "WIPRO":     "3787",
    "BAJAJ-AUTO":"16669",
    "MARUTI":    "10999",
    "ICICIBANK": "4963",
    "TATAMOTORS":"3456",
    "AXISBANK":  "5900",
    "KOTAKBANK": "1922",
    "SBIN":      "3045",
    "HINDUNILVR":"1394",
    "ITC":       "1660",
    "BHARTIARTL":"10604",
}


class AngelOneFeed:
    """
    Real-time NSE tick feed using Angel One Smart API WebSocket.
    Drop-in replacement for YFinanceFeed — same interface.

    Usage:
        feed = AngelOneFeed(
            symbols=["RELIANCE", "TCS"],
            api_key="your_api_key",
            client_id="your_client_id",
            password="your_mpin",
            totp_secret="your_totp_secret",
        )
        feed.on_tick(callback)
        feed.start()

    To get credentials:
        1. Log into Angel One → My Profile → API Access
        2. Generate API key
        3. client_id = your Angel One client ID (e.g. A123456)
        4. password = your 4-digit MPIN
        5. totp_secret = TOTP secret from Angel One authenticator setup
    """

    def __init__(
        self,
        symbols: list[str],
        api_key: str,
        client_id: str,
        password: str,
        totp_secret: str,
    ):
        if not ANGEL_AVAILABLE:
            raise RuntimeError(
                "smartapi-python not installed. Run: pip3.11 install smartapi-python"
            )
        self.symbols = [s.upper() for s in symbols]
        self.api_key = api_key
        self.client_id = client_id
        self.password = password
        self.totp_secret = totp_secret

        self._callbacks: list[Callable[[dict], None]] = []
        self._stop_event = threading.Event()
        self._smart_api: SmartConnect | None = None
        self._ws: SmartWebSocketV2 | None = None
        self._auth_token: str = ""
        self._feed_token: str = ""

    def on_tick(self, callback: Callable[[dict], None]) -> None:
        self._callbacks.append(callback)

    def _authenticate(self) -> bool:
        import pyotp
        try:
            self._smart_api = SmartConnect(api_key=self.api_key)
            totp = pyotp.TOTP(self.totp_secret).now()
            data = self._smart_api.generateSession(self.client_id, self.password, totp)
            if data["status"]:
                self._auth_token = data["data"]["jwtToken"]
                self._feed_token = self._smart_api.getfeedToken()
                logger.info("Angel One authenticated successfully")
                return True
            else:
                logger.error("Angel One auth failed: %s", data)
                return False
        except Exception as exc:
            logger.error("Angel One auth exception: %s", exc)
            return False

    def _on_ws_data(self, wsapp, message) -> None:
        try:
            token = str(message.get("token", ""))
            symbol = next(
                (s for s, t in NSE_TOKEN_MAP.items() if t == token and s in self.symbols),
                None,
            )
            if not symbol:
                return
            ltp = float(message.get("last_traded_price", 0)) / 100.0
            open_price = float(message.get("open_price_of_the_day", 0)) / 100.0
            high = float(message.get("high_price_of_the_day", 0)) / 100.0
            low = float(message.get("low_price_of_the_day", 0)) / 100.0
            volume = int(message.get("volume_trade_for_the_day", 0))
            best_bid = float(message.get("best_5_buy_data", [{}])[0].get("price", ltp)) / 100.0
            best_ask = float(message.get("best_5_sell_data", [{}])[0].get("price", ltp)) / 100.0

            bar = {
                "symbol": symbol,
                "open": open_price,
                "high": high,
                "low": low,
                "close": ltp,
                "volume": float(volume),
                "best_bid": best_bid,
                "best_ask": best_ask,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            for cb in self._callbacks:
                cb(bar)
        except Exception as exc:
            logger.warning("AngelOneFeed tick parse error: %s", exc)

    def _on_ws_error(self, wsapp, error) -> None:
        logger.error("AngelOneFeed WebSocket error: %s", error)

    def _on_ws_close(self, wsapp) -> None:
        logger.warning("AngelOneFeed WebSocket closed")
        if not self._stop_event.is_set():
            logger.info("Attempting reconnect in 5s...")
            time.sleep(5)
            self._connect_ws()

    def _on_ws_open(self, wsapp) -> None:
        logger.info("AngelOneFeed WebSocket connected")
        tokens = [
            {"exchangeType": 1, "tokens": [NSE_TOKEN_MAP[s] for s in self.symbols if s in NSE_TOKEN_MAP]}
        ]
        self._ws.subscribe("angel_feed", 3, tokens)  # mode 3 = full snap quote

    def _connect_ws(self) -> None:
        tokens = [NSE_TOKEN_MAP[s] for s in self.symbols if s in NSE_TOKEN_MAP]
        self._ws = SmartWebSocketV2(
            self._auth_token,
            self.api_key,
            self.client_id,
            self._feed_token,
        )
        self._ws.on_open = self._on_ws_open
        self._ws.on_data = self._on_ws_data
        self._ws.on_error = self._on_ws_error
        self._ws.on_close = self._on_ws_close
        self._ws.connect()

    def start(self) -> None:
        if not self._authenticate():
            raise RuntimeError("Angel One authentication failed — check credentials")
        threading.Thread(target=self._connect_ws, daemon=True).start()
        logger.info("AngelOneFeed started for %s", self.symbols)

    def stop(self) -> None:
        self._stop_event.set()
        if self._ws:
            try:
                self._ws.close_connection()
            except Exception:
                pass
        logger.info("AngelOneFeed stopped")
