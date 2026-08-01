"""Market data for the paper-trading harness.

Sandbox provides NO market data (verified in Step 0), so this module pulls
read-only live data from Upstox's market-quote API:

  1. daily close capture at ~15:32 IST — extends the signal's close series
     (seeded from backend/data/nifty50_data/*.csv, the same data the backtest
     used). A "trading day" is defined as a day where >= 40 of 49 closes were
     captured — self-calibrating against holidays/closures, no calendar needed.
  2. bid/ask reference quotes at order-submission time — the slippage yardstick
     (live midpoint is the reference price for realized-cost measurement).

Quote parsing is defensive: the v2 quote payload schema is extracted with
fallbacks (last_price is always the floor).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import config
from .token_store import TokenStore

MIN_CAPTURE_COUNT = 40  # of 49 symbols must capture for a valid trading day


def _num(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_quote(payload: dict) -> dict:
    """Normalize one instrument's quote payload to
    {last, open, high, low, close, bid, ask, depth_ok} with None-safe fields."""
    ohlc = payload.get("ohlc") or {}
    last = _num(payload.get("last_price"))
    out = {
        "last": last,
        "open": _num(ohlc.get("open")),
        "high": _num(ohlc.get("high")),
        "low": _num(ohlc.get("low")),
        "close": _num(ohlc.get("close")),
        "bid": None,
        "ask": None,
        "depth_ok": False,
    }
    depth = payload.get("depth") or {}
    orders = depth.get("market_orders") or []
    for o in orders:
        price = _num(o.get("price"))
        side = (o.get("order_side") or o.get("type") or "").lower()
        qty = _num(o.get("quantity"))
        if price is None:
            continue
        if side == "buy":
            if out["bid"] is None or price > out["bid"]:
                out["bid"] = price
        elif side == "sell":
            if out["ask"] is None or (out["ask"] and price < out["ask"]):
                out["ask"] = price
    # Alternative depth keys used by some v2 responses
    bid = _num(payload.get("depth", {}).get("bid"))
    ask = _num(payload.get("depth", {}).get("ask"))
    if bid is not None:
        out["bid"] = bid
    if ask is not None:
        out["ask"] = ask
    if out["bid"] is not None and out["ask"] is not None and out["ask"] > out["bid"]:
        out["depth_ok"] = True
    return out


def midpoint(quote: dict) -> float | None:
    if quote.get("depth_ok"):
        return (quote["bid"] + quote["ask"]) / 2.0
    return quote.get("last")


class QuoteCache:
    """Fetches quotes for all universe symbols, keyed by symbol."""

    def __init__(self, marketdata_client, instrument_map: dict[str, str]):
        self.client = marketdata_client
        self.instrument_map = instrument_map

    def fetch(self, token: str) -> tuple[dict[str, dict], list[str]]:
        """Returns ({symbol: normalized_quote}, failed_symbols)."""
        keys = list(self.instrument_map.values())
        quotes: dict[str, dict] = {}
        failed: list[str] = []
        try:
            body = self.client.quotes(token, keys)
        except Exception:
            return {}, list(self.instrument_map.keys())
        data = body.get("data") or {}
        rev = {v: k for k, v in self.instrument_map.items()}
        for key, payload in data.items():
            sym = rev.get(key) or rev.get(key.split("|")[-1])
            if sym:
                quotes[sym] = parse_quote(payload)
        failed = [s for s in self.instrument_map if s not in quotes]
        return quotes, failed


class CloseHistory:
    """Per-symbol daily close series used by the signal.

    Seeded once from the repo CSVs (same data as the backtest), then appended
    from live close captures. Stored as JSON: {"seed_date": ..., "series": {
    "SYM": [[date, close], ...], ...}}.
    """

    def __init__(self, path: Path | None = None):
        self.path = Path(path or config.CLOSE_HISTORY_FILE)
        self.series: dict[str, list[list]] = {}
        self.seed_date: str | None = None

    def exists(self) -> bool:
        return self.path.exists()

    def seed_from_csv(self, symbols: list[str]) -> int:
        """Seed from backend/data/nifty50_data/*.csv (repo backtest data)."""
        n = 0
        for sym in symbols:
            csv = config.DATA_DIR_50 / f"{sym}.csv"
            if not csv.exists():
                continue
            rows = []
            for line in csv.read_text().splitlines()[1:]:
                parts = line.split(",")
                if len(parts) < 6:
                    continue
                try:
                    close = float(parts[4])
                except ValueError:
                    continue
                rows.append([parts[0], close])
            if rows:
                self.series[sym] = rows
                n += 1
        self.seed_date = self.series.get(symbols[0], [["", 0]])[-1][0]
        self.save()
        return n

    def load(self) -> bool:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text())
                self.series = {k: [list(r) for r in v] for k, v in
                               data.get("series", {}).items()}
                self.seed_date = data.get("seed_date")
                return bool(self.series)
        except Exception:  # noqa: BLE001
            pass
        return False

    def append_day(self, date: str, closes: dict[str, float]) -> int:
        """Append a captured day. Skips symbols that already have this date."""
        n = 0
        for sym, close in closes.items():
            series = self.series.setdefault(sym, [])
            if series and series[-1][0] == date:
                continue
            if close is not None and close > 0:
                series.append([date, close])
                n += 1
        self.save()
        return n

    def latest_date(self) -> str | None:
        dates = [r[0] for s in self.series.values() for r in s[-1:]]
        return max(dates) if dates else self.seed_date

    def trailing_return(self, symbol: str, lookback: int, as_of: str | None = None) -> float | None:
        """pct_change(lookback) of closes, using the last completed close at or
        before `as_of` (inclusive). Mirrors backtest: pct_change(20)."""
        series = self.series.get(symbol)
        if not series:
            return None
        closes = [c for d, c in series if as_of is None or d <= as_of]
        if len(closes) < lookback + 1:
            return None
        ref = closes[-1]
        past = closes[-1 - lookback]
        if past <= 0:
            return None
        return (ref - past) / past

    def symbol_last_close(self, symbol: str) -> float | None:
        series = self.series.get(symbol)
        return series[-1][1] if series else None

    def count_trading_days_since(self, since_date: str | None) -> int:
        """Number of captured trading days after `since_date` (exclusive)."""
        if not since_date:
            return len(self._common_dates())
        dates = self._common_dates()
        return sum(1 for d in dates if d > since_date)

    def _common_dates(self) -> list[str]:
        if not self.series:
            return []
        # dates common to the majority of symbols (>= MIN_CAPTURE_COUNT)
        from collections import Counter
        cnt = Counter(d for sym in self.series for d, _ in self.series[sym])
        return sorted(d for d, c in cnt.items() if c >= MIN_CAPTURE_COUNT)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"seed_date": self.seed_date,
                                   "series": self.series}))
        tmp.replace(self.path)
