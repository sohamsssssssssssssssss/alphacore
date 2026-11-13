"""
Upstox instrument-key resolution (instrument-key resolution ONLY).

Source of truth: Upstox's published NSE instrument master — a gzipped JSON
list of every NSE instrument:

    https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz

(URL verified against https://upstox.com/developer/api-documentation/instruments/
on 2026-08-15. The docs' sample EQ object shows RELIANCE with
instrument_key "NSE_EQ|INE002A01018" — the key is "<segment>|<ISIN>", NOT a
numeric exchange token.)

For cash equities (segment == "NSE_EQ", instrument_type == "EQ") we map
trading_symbol -> instrument_key and cache that lookup to
`instruments_cache.json` (a gitignored runtime artifact) so re-runs don't
re-download the ~2 MB gzipped master.

FAIL-LOUD policy: if a symbol cannot be resolved from the real master we
RAISE — never fall back to guessed numeric tokens. A guessed key that gets
silently rejected by the order API is worse than an explicit skip.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

INSTRUMENT_MASTER_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
DEFAULT_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instruments_cache.json")
MAX_CACHE_AGE_DAYS = 7
DOWNLOAD_TIMEOUT_SECONDS = 60

CACHE_META_DOWNLOADED_AT = "_downloaded_at"
CACHE_META_LOOKUP = "lookup"
# Every instrument in our lookup is an NSE cash-equity, so keys must carry the
# NSE_EQ|<ISIN> prefix. Any cache value without it is stale/wrong (e.g. the old
# symbol->ISIN or symbol->numeric formats) and must be re-downloaded.
KEY_PREFIX = "NSE_EQ|"


def build_lookup(records: list[dict]) -> dict[str, str]:
    """Map trading_symbol -> instrument_key for NSE cash-equity (EQ) instruments."""
    lookup: dict[str, str] = {}
    for rec in records:
        if rec.get("segment") != "NSE_EQ" or rec.get("instrument_type") != "EQ":
            continue
        symbol = (rec.get("trading_symbol") or "").strip().upper()
        key = rec.get("instrument_key") or ""
        if not symbol or not key:
            continue
        if symbol in lookup and lookup[symbol] != key:
            logger.warning("duplicate trading_symbol %s in master: %s vs %s (keeping first)",
                           symbol, lookup[symbol], key)
        else:
            lookup.setdefault(symbol, key)
    return lookup


def download_master(url: str = INSTRUMENT_MASTER_URL) -> dict[str, str]:
    """Download the gzipped NSE instrument master and build the EQ lookup."""
    resp = requests.get(url, timeout=DOWNLOAD_TIMEOUT_SECONDS)
    resp.raise_for_status()
    records = json.loads(gzip.decompress(resp.content))
    lookup = build_lookup(records)
    if not lookup:
        raise RuntimeError(f"instrument master at {url} contained no NSE_EQ/EQ instruments")
    return lookup


def _cache_valid(path: str, max_age_days: int = MAX_CACHE_AGE_DAYS) -> bool:
    """True if the cache holds a non-empty, correctly-formatted lookup that is fresh enough."""
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        lookup = data.get(CACHE_META_LOOKUP) if isinstance(data, dict) else data
        if not isinstance(lookup, dict) or not lookup:
            return False
        if not all(isinstance(k, str) and isinstance(v, str) and v.startswith(KEY_PREFIX)
                   for k, v in lookup.items()):
            logger.warning("instrument cache %s holds non-NSE_EQ keys; treating as stale", path)
            return False
        at = data.get(CACHE_META_DOWNLOADED_AT) if isinstance(data, dict) else None
        if at:
            dt = datetime.fromisoformat(str(at))
            if datetime.now() - dt > timedelta(days=max_age_days):
                return False
        return True
    except Exception as exc:
        logger.warning("invalid instrument cache %s: %s", path, exc)
        return False


def _read_lookup(cache_path: str) -> dict[str, str]:
    with open(cache_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    lookup = data.get(CACHE_META_LOOKUP) if isinstance(data, dict) else data
    return dict(lookup) if isinstance(lookup, dict) else {}


def load_instrument_lookup(cache_path: str = DEFAULT_CACHE_PATH, force: bool = False) -> dict[str, str]:
    """Return symbol -> instrument_key, downloading + caching the master as needed.

    Fail-loud: raises if the master cannot be obtained and no usable cache
    exists. On a network failure with a usable (possibly stale) cache, falls
    back to the cache with a clear warning — the cache is still real master
    data, never a guess.
    """
    if not force and _cache_valid(cache_path):
        lookup = _read_lookup(cache_path)
        print(f"[DATA] Instrument master: using cached lookup ({len(lookup)} NSE_EQ instruments) "
              f"-> {cache_path}")
        return lookup

    try:
        lookup = download_master()
    except Exception as exc:
        if not force and _cache_valid(cache_path):
            lookup = _read_lookup(cache_path)
            print(f"[DATA] WARNING: instrument master download failed ({exc}); "
                  f"using cached lookup ({len(lookup)} instruments) — keys may be stale")
            return lookup
        raise RuntimeError(
            "FAIL-LOUD: could not obtain the Upstox instrument master from "
            f"{INSTRUMENT_MASTER_URL}: {exc}. Refusing to guess instrument keys."
        ) from exc

    payload = {
        CACHE_META_DOWNLOADED_AT: datetime.now().astimezone().isoformat(timespec="seconds"),
        CACHE_META_LOOKUP: lookup,
    }
    try:
        with open(cache_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
        print(f"[DATA] Instrument master: downloaded {len(lookup)} NSE_EQ instruments "
              f"-> {cache_path}")
    except Exception as exc:
        logger.warning("could not write instrument cache %s: %s", cache_path, exc)
    return lookup


def resolve_instrument_keys(symbols: list[str], cache_path: str = DEFAULT_CACHE_PATH,
                            force: bool = False) -> dict[str, str]:
    """Resolve every requested symbol to its real Upstox instrument_key.

    FAILS LOUD (RuntimeError) listing any unresolvable symbol — no
    numeric-token fallback, ever.
    """
    lookup = load_instrument_lookup(cache_path, force=force)
    seen: list[str] = []
    for s in symbols:
        if s not in seen:
            seen.append(s)
    missing = [s for s in seen if s not in lookup]
    if missing:
        raise RuntimeError(
            "FAIL-LOUD: no Upstox instrument_key in the instrument master for: "
            f"{sorted(missing)} (master: {INSTRUMENT_MASTER_URL}). "
            "Refusing to guess numeric tokens. Fix the symbol (e.g. post-demerger rename) "
            "or verify the master before trading."
        )
    return {s: lookup[s] for s in seen}
