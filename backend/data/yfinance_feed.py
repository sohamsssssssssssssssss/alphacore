from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime, time as dt_time, timedelta, timezone
import zoneinfo
from typing import Callable

import yfinance as yf

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30), name="IST")


class MarketHoursChecker:
    @staticmethod
    def now_ist() -> datetime:
        return datetime.now(IST)

    @classmethod
    def is_market_open(cls) -> bool:
        now = cls.now_ist()
        if now.weekday() >= 5:
            return False
        market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
        market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
        return market_open <= now <= market_close

    @classmethod
    def next_open_seconds(cls) -> float:
        now = cls.now_ist()
        target = now.replace(hour=9, minute=15, second=0, microsecond=0)

        if now.weekday() >= 5:
            days_ahead = 7 - now.weekday()
            target = target + timedelta(days=days_ahead)
        elif now.time() < dt_time(9, 15):
            pass
        else:
            target = target + timedelta(days=1)
            while target.weekday() >= 5:
                target = target + timedelta(days=1)

        return max(0.0, (target - now).total_seconds())


class YFinanceFeed:
    def __init__(self, symbols: list[str], interval: str = "1m", poll_interval_seconds: float = 60.0):
        self.symbols = [s.upper() for s in symbols]
        self._yf_symbols = {}
        for s in symbols:
            sym = s.upper()
            if sym == "TATAMOTORS":
                self._yf_symbols[sym] = self._resolve_tatamotors_ticker()
            else:
                self._yf_symbols[sym] = sym if sym.endswith(".NS") else f"{sym}.NS"
        self.interval = interval
        self.poll_interval_seconds = float(poll_interval_seconds)

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._callbacks: list[Callable[[dict], None]] = []
        self._latest: dict[str, dict] = {}
        self._last_ts: dict[str, datetime] = {}
        self._lock = threading.Lock()

    def _resolve_tatamotors_ticker(self) -> str:
        candidates = ["TATAMOTORS.NS", "TATAMOTORS.BO"]
        for cand in candidates:
            try:
                df = yf.download(cand, period="5d", interval="1d", progress=False)
                if df is not None and not df.empty:
                    return cand
            except Exception:
                continue
        return "TATAMOTORS.NS"

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="yfinance-feed")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def get_latest(self, symbol: str) -> dict | None:
        with self._lock:
            return self._latest.get(symbol.upper())

    def on_tick(self, callback: Callable[[dict], None]) -> None:
        self._callbacks.append(callback)

    def _run_loop(self) -> None:
        checker = MarketHoursChecker
        while not self._stop_event.is_set():
            print(f"[FEED] Polling at {datetime.now()}, market open: {checker.is_market_open()}")
            if checker.is_market_open():
                self._poll_once()
            else:
                wait_secs = checker.next_open_seconds()
                logger.info("Market closed. Next open in %.0f seconds.", wait_secs)
                print(f"[FEED] Market closed. Sleeping {wait_secs:.0f}s until next open.")
                self._stop_event.wait(min(wait_secs, self.poll_interval_seconds))
                continue
            self._stop_event.wait(self.poll_interval_seconds)

    def _poll_once(self) -> None:
        for symbol in self.symbols:
            yf_symbol = self._yf_symbols[symbol]
            try:
                df = yf.download(yf_symbol, period="1d", interval=self.interval, progress=False)
            except Exception as exc:
                logger.warning("yfinance fetch failed for %s: %s", yf_symbol, exc)
                continue

            print(f"[FEED] Got {len(df)} rows for {symbol}")
            if (df is None or df.empty) and symbol == "TATAMOTORS":
                alt = "TATAMOTORS.BO" if yf_symbol.endswith(".NS") else "TATAMOTORS.NS"
                try:
                    df_alt = yf.download(alt, period="1d", interval=self.interval, progress=False)
                    if df_alt is not None and not df_alt.empty:
                        self._yf_symbols[symbol] = alt
                        yf_symbol = alt
                        df = df_alt
                        print(f"[FEED] Switched {symbol} ticker to {alt}")
                except Exception:
                    pass

            if df is None or df.empty:
                continue

            row = df.iloc[-1]
            ts = df.index[-1]
            if hasattr(ts, "to_pydatetime"):
                ts = ts.to_pydatetime()
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=IST)
            ts_utc = ts.astimezone(UTC)

            last_seen = self._last_ts.get(symbol)
            if last_seen is not None and ts_utc <= last_seen:
                continue

            tick = {
                "symbol": symbol,
                "open": float(row["Open"].iloc[0] if hasattr(row["Open"], "iloc") else row["Open"]),
                "high": float(row["High"].iloc[0] if hasattr(row["High"], "iloc") else row["High"]),
                "low": float(row["Low"].iloc[0] if hasattr(row["Low"], "iloc") else row["Low"]),
                "close": float(row["Close"].iloc[0] if hasattr(row["Close"], "iloc") else row["Close"]),
                "volume": float(row["Volume"].iloc[0] if hasattr(row["Volume"], "iloc") else row["Volume"]),
                "timestamp": ts_utc.isoformat(),
            }
            bar = tick

            with self._lock:
                self._latest[symbol] = tick
                self._last_ts[symbol] = ts_utc

            print(f"[FEED] New tick for {symbol}: {bar}")
            for cb in list(self._callbacks):
                try:
                    cb(tick)
                except Exception:
                    logger.exception("on_tick callback failed for %s", symbol)
