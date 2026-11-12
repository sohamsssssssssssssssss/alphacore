from __future__ import annotations

from universe import (
    EXCLUDED_SYMBOL,
    UNIVERSE_49,
    UPSTOX_NSE_EQ_TOKEN,
    isin_instrument_key,
    numeric_instrument_key,
)


def test_universe_has_49_symbols():
    assert len(UNIVERSE_49) == 49
    assert len(set(UNIVERSE_49)) == 49  # no duplicates


def test_sbilife_is_excluded():
    assert EXCLUDED_SYMBOL not in UNIVERSE_49
    assert "SBILIFE" not in UNIVERSE_49


def test_every_symbol_has_a_numeric_token():
    for sym in UNIVERSE_49:
        assert sym in UPSTOX_NSE_EQ_TOKEN, f"missing token for {sym}"


def test_numeric_instrument_key_format():
    assert numeric_instrument_key("RELIANCE") == "NSE_EQ|2885"
    assert numeric_instrument_key("SBIN") == "NSE_EQ|3045"


def test_isin_instrument_key_format():
    assert isin_instrument_key("RELIANCE", "INE002a01018") == "NSE_EQ|INE002A01018"
