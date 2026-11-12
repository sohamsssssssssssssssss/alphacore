from __future__ import annotations

import gzip
import json
from datetime import datetime, timedelta

import pytest

import instruments
from instruments import (
    INSTRUMENT_MASTER_URL,
    build_lookup,
    load_instrument_lookup,
    resolve_instrument_keys,
)


def _records() -> list[dict]:
    return [
        {"segment": "NSE_EQ", "instrument_type": "EQ", "trading_symbol": "RELIANCE",
         "instrument_key": "NSE_EQ|INE002A01018", "exchange_token": "2885"},
        {"segment": "NSE_EQ", "instrument_type": "EQ", "trading_symbol": "HCLTECH",
         "instrument_key": "NSE_EQ|INE860A01027", "exchange_token": "7229"},
        # BE (block deal) entries share the ISIN — must be excluded; EQ wins.
        {"segment": "NSE_EQ", "instrument_type": "BE", "trading_symbol": "RELIANCE",
         "instrument_key": "NSE_EQ|INE002A01018", "exchange_token": "16931"},
        # Non-equity segments must be excluded.
        {"segment": "NSE_FO", "instrument_type": "FUT", "trading_symbol": "NIFTY",
         "instrument_key": "NSE_FO|12345"},
        # Non-EQ instrument types (e.g. state govt securities) must be excluded.
        {"segment": "NSE_EQ", "instrument_type": "SG", "trading_symbol": "749RJ35",
         "instrument_key": "NSE_EQ|IN2920250163"},
        # trading_symbol is case-insensitive in the master.
        {"segment": "NSE_EQ", "instrument_type": "EQ", "trading_symbol": "tcs",
         "instrument_key": "NSE_EQ|INE467B01029", "exchange_token": "11536"},
    ]


def _write_cache(path, lookup, downloaded_at: str | None = None) -> None:
    payload = {instruments.CACHE_META_LOOKUP: lookup}
    if downloaded_at:
        payload[instruments.CACHE_META_DOWNLOADED_AT] = downloaded_at
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)


class _FakeResp:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self):
        pass


def _monkeypatch_download(monkeypatch, records: list[dict]) -> None:
    raw = gzip.compress(json.dumps(records).encode("utf-8"))
    monkeypatch.setattr("instruments.requests.get", lambda url, timeout: _FakeResp(raw))


def test_build_lookup_filters_nse_eq_eq_only():
    lookup = build_lookup(_records())
    assert lookup == {
        "RELIANCE": "NSE_EQ|INE002A01018",
        "HCLTECH": "NSE_EQ|INE860A01027",
        "TCS": "NSE_EQ|INE467B01029",
    }


def test_build_lookup_keeps_first_on_duplicate_symbol():
    records = _records() + [
        {"segment": "NSE_EQ", "instrument_type": "EQ", "trading_symbol": "TCS",
         "instrument_key": "NSE_EQ|SOMEOTHERKEY"},
    ]
    assert build_lookup(records)["TCS"] == "NSE_EQ|INE467B01029"


def test_load_instrument_lookup_downloads_and_caches(tmp_path, monkeypatch):
    _monkeypatch_download(monkeypatch, _records())
    cache = tmp_path / "instruments_cache.json"
    lookup = load_instrument_lookup(str(cache), force=True)
    assert lookup["RELIANCE"] == "NSE_EQ|INE002A01018"
    assert lookup["HCLTECH"] == "NSE_EQ|INE860A01027"
    assert lookup["TCS"] == "NSE_EQ|INE467B01029"
    # Cache written with metadata + lookup.
    data = json.loads(cache.read_text())
    assert data[instruments.CACHE_META_DOWNLOADED_AT]
    assert data[instruments.CACHE_META_LOOKUP] == lookup


def test_load_instrument_lookup_uses_fresh_cache_without_network(tmp_path, monkeypatch):
    cache = tmp_path / "instruments_cache.json"
    _write_cache(cache, {"RELIANCE": "NSE_EQ|INE002A01018"})

    def _boom(*a, **k):
        raise AssertionError("network must not be hit when cache is fresh")

    monkeypatch.setattr("instruments.requests.get", _boom)
    lookup = load_instrument_lookup(str(cache))
    assert lookup == {"RELIANCE": "NSE_EQ|INE002A01018"}


def test_load_instrument_lookup_redownloads_stale_or_wrong_format_cache(tmp_path, monkeypatch):
    cache = tmp_path / "instruments_cache.json"
    # Old-style cache (symbol -> bare ISIN, no NSE_EQ| prefix): must be rejected.
    _write_cache(cache, {"RELIANCE": "INE002A01018"})
    _monkeypatch_download(monkeypatch, _records())
    lookup = load_instrument_lookup(str(cache))
    assert lookup["RELIANCE"] == "NSE_EQ|INE002A01018"  # re-downloaded, not the bare ISIN
    data = json.loads(cache.read_text())
    assert data[instruments.CACHE_META_LOOKUP]["RELIANCE"].startswith("NSE_EQ|")

    # Expired cache: must be re-downloaded too.
    expired = datetime.now() - timedelta(days=instruments.MAX_CACHE_AGE_DAYS + 1)
    _write_cache(cache, {"HCLTECH": "NSE_EQ|INE860A01027"},
                 downloaded_at=expired.isoformat())
    lookup = load_instrument_lookup(str(cache))
    assert "RELIANCE" in lookup  # fresh download contains the full master
    assert lookup["HCLTECH"] == "NSE_EQ|INE860A01027"


def test_load_instrument_lookup_fails_loud_on_download_failure_no_cache(tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr("instruments.requests.get", _boom)
    with pytest.raises(RuntimeError, match="FAIL-LOUD"):
        load_instrument_lookup(str(tmp_path / "no_such_cache.json"))


def test_load_instrument_lookup_falls_back_to_cache_on_download_failure(tmp_path, monkeypatch):
    cache = tmp_path / "instruments_cache.json"
    _write_cache(cache, {"RELIANCE": "NSE_EQ|INE002A01018"})

    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr("instruments.requests.get", _boom)
    lookup = load_instrument_lookup(str(cache))
    assert lookup == {"RELIANCE": "NSE_EQ|INE002A01018"}


def test_resolve_instrument_keys_fails_loud_on_missing_symbol(tmp_path):
    cache = tmp_path / "instruments_cache.json"
    _write_cache(cache, {"RELIANCE": "NSE_EQ|INE002A01018"})
    with pytest.raises(RuntimeError) as exc:
        resolve_instrument_keys(["RELIANCE", "MADEUPSYM"], str(cache))
    assert "MADEUPSYM" in str(exc.value)
    assert INSTRUMENT_MASTER_URL in str(exc.value)
    assert "FAIL-LOUD" in str(exc.value)


def test_resolve_instrument_keys_dedupes_and_preserves_order(tmp_path):
    cache = tmp_path / "instruments_cache.json"
    _write_cache(cache, {"A": "NSE_EQ|INEAAAA", "B": "NSE_EQ|INEBBBB"})
    result = resolve_instrument_keys(["B", "A", "B"], str(cache))
    assert list(result.keys()) == ["B", "A"]
    assert result["A"] == "NSE_EQ|INEAAAA"
