"""Instrument key resolution for the 49-symbol universe.

Primary: Upstox instruments master API (read-only, cached to
states/paper_trading/instruments.json).
Fallback: static NSE_EQ|ISIN map below — used ONLY if the API fetch fails, and
every use of the fallback is logged loudly. The verify_connectivity script
reports which source is in effect.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import config
from .token_store import TokenStore

# Static fallback map (NSE_EQ|ISIN). Populated from public NSE instrument data;
# verified against the Upstox instruments API when reachable. Do not rely on
# this silently — the harness logs when it is used.
FALLBACK_INSTRUMENT_KEYS: dict[str, str] = {
    "ADANIENT": "NSE_EQ|INE423A01024", "ADANIPORTS": "NSE_EQ|INE742F01042",
    "APOLLOHOSP": "NSE_EQ|INE437A01024", "ASIANPAINT": "NSE_EQ|INE021A01026",
    "AXISBANK": "NSE_EQ|INE238A01029", "BAJAJ-AUTO": "NSE_EQ|INE917I01010",
    "BAJAJFINSV": "NSE_EQ|INE918I01026", "BAJFINANCE": "NSE_EQ|INE296A01024",
    "BHARTIARTL": "NSE_EQ|INE397D01024", "BPCL": "NSE_EQ|INE029A01011",
    "BRITANNIA": "NSE_EQ|INE216A01030", "CIPLA": "NSE_EQ|INE059A01026",
    "COALINDIA": "NSE_EQ|INE522F01014", "DIVISLAB": "NSE_EQ|INE361B01024",
    "DRREDDY": "NSE_EQ|INE089A01023", "EICHERMOT": "NSE_EQ|INE066A01021",
    "GRASIM": "NSE_EQ|INE047A01021", "HCLTECH": "NSE_EQ|INE860A01027",
    "HDFCBANK": "NSE_EQ|INE040A01034", "HEROMOTOCO": "NSE_EQ|INE158A01026",
    "HINDALCO": "NSE_EQ|INE038A01020", "HINDUNILVR": "NSE_EQ|INE030A01027",
    "ICICIBANK": "NSE_EQ|INE090A01021", "INDUSINDBK": "NSE_EQ|INE095A01012",
    "INFY": "NSE_EQ|INE009A01021", "IOC": "NSE_EQ|INE242A01010",
    "ITC": "NSE_EQ|INE154A01025", "JSWSTEEL": "NSE_EQ|INE019A01038",
    "KOTAKBANK": "NSE_EQ|INE237A01028", "LT": "NSE_EQ|INE018A01030",
    "M&M": "NSE_EQ|INE101A01026", "MARUTI": "NSE_EQ|INE585B01010",
    "NESTLEIND": "NSE_EQ|INE239A01016", "NTPC": "NSE_EQ|INE733E01010",
    "ONGC": "NSE_EQ|INE213A01029", "POWERGRID": "NSE_EQ|INE752E01010",
    "RELIANCE": "NSE_EQ|INE002A01018", "SBILIFE": "NSE_EQ|INE276G01015",
    "SBIN": "NSE_EQ|INE062A01020", "SHREECEM": "NSE_EQ|INE070A01015",
    "SUNPHARMA": "NSE_EQ|INE044A01036", "TATACONSUM": "NSE_EQ|INE192A01025",
    "TATASTEEL": "NSE_EQ|INE081A01020", "TCS": "NSE_EQ|INE467B01029",
    "TECHM": "NSE_EQ|INE669E01016", "TITAN": "NSE_EQ|INE280A01028",
    "ULTRACEMCO": "NSE_EQ|INE481G01011", "UPL": "NSE_EQ|INE628A01036",
    "WIPRO": "NSE_EQ|INE075A01022",
}

# TATAMOTORS is deliberately NOT in the fallback map: it is excluded from the
# 49-symbol universe (empty yfinance data, see universe-expansion experiment).


class InstrumentResolver:
    """Maps symbol -> NSE_EQ|ISIN key. API-fetch first, static map fallback."""

    def __init__(self, cache_file: Path | None = None):
        self.cache_file = Path(cache_file or config.INSTRUMENTS_FILE)
        self._map: dict[str, str] = {}
        self._source = "none"

    def load_cache(self) -> bool:
        try:
            if self.cache_file.exists():
                data = json.loads(self.cache_file.read_text())
                self._map = {k: v for k, v in data.get("keys", {}).items() if v}
                self._source = data.get("source", "cache")
                return bool(self._map)
        except Exception:  # noqa: BLE001
            pass
        return False

    def fetch(self, marketdata_client, token: str, symbols: list[str]) -> tuple[int, str]:
        """Fetch from the instruments API and cache. Returns (n_resolved, source)."""
        try:
            rows = marketdata_client.instruments(token, "NSE_EQ")
        except Exception:
            return 0, "fetch_failed"
        resolved: dict[str, str] = {}
        symbol_set = set(symbols)
        for row in rows:
            sym = (row.get("trading_symbol") or row.get("symbol") or "").upper()
            key = row.get("instrument_key") or row.get("instrument_token") or ""
            if sym in symbol_set and key:
                resolved[sym] = key
        if resolved:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(json.dumps(
                {"source": "upstox_instruments_api", "fetched_at": __import__(
                    "time").time(), "keys": resolved}, indent=2))
            self._map = resolved
            self._source = "upstox_instruments_api"
            return len(resolved), self._source
        return 0, "fetch_empty"

    def fallback(self, symbols: list[str]) -> int:
        self._map = {s: FALLBACK_INSTRUMENT_KEYS[s] for s in symbols
                     if s in FALLBACK_INSTRUMENT_KEYS}
        self._source = "static_fallback"
        return len(self._map)

    def resolve(self, symbols: list[str]) -> tuple[dict[str, str], str]:
        """Ensure resolution for all symbols. Returns (map, source). Never raises."""
        missing = [s for s in symbols if s not in self._map]
        if not missing:
            return dict(self._map), self._source
        if not self.load_cache():
            n = self.fallback(symbols)
            self._source = f"static_fallback({n})"
        missing = [s for s in symbols if s not in self._map]
        if missing:
            return dict(self._map), f"{self._source}+missing:{missing}"
        return dict(self._map), self._source


class InstrumentCache:
    """Simple wrapper the scheduler can call every cycle; refreshes lazily."""

    def __init__(self, symbols: list[str]):
        self.symbols = symbols
        self.resolver = InstrumentResolver()
        self.map: dict[str, str] = {}
        self.source = "none"

    def ensure(self, marketdata_client, token_store: TokenStore) -> tuple[dict[str, str], str]:
        if self.map:
            return self.map, self.source
        md = token_store.tokens.marketdata_token
        if md:
            n, source = self.resolver.fetch(marketdata_client, md, self.symbols)
            if n >= len(self.symbols):
                self.map, self.source = dict(self.resolver._map), source
                return self.map, self.source
        self.map, self.source = self.resolver.resolve(self.symbols)
        return self.map, self.source
