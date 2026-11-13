"""
49-symbol universe for the K=1 cross-sectional relative-strength paper test.

Universe = Nifty 50 MINUS SBILIFE (SBILIFE was the symbol excluded in the
-1.57 Sharpe backtest per the research notes — shortest daily history,
listed only in 2021).

Instrument keys: the harness resolves order instrument keys from Upstox's
published instrument master (instruments.py) — the master maps each
NSE_EQ trading_symbol to its real instrument_key "NSE_EQ|<ISIN>" (e.g.
RELIANCE -> "NSE_EQ|INE002A01018"), which is the form the v2 order/place
API requires. Unresolvable symbols FAIL LOUD; there is no fallback.

UPSTOX_NSE_EQ_TOKEN below is a HISTORICAL snapshot of the numeric NSE_EQ
exchange tokens (canonical copy in backend/data/nifty50_symbols.py,
NIFTY50_TOKEN_MAP). The numbers still match the master's exchange_token
field, but "NSE_EQ|<numeric>" is NOT a valid instrument_key for order
placement — it is kept here as a reference only and is no longer used by
the harness to build order payloads.
"""

from __future__ import annotations

# Nifty 50 symbols minus SBILIFE = 49 symbols.
UNIVERSE_49: list[str] = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
    "AXISBANK", "WIPRO", "MARUTI", "BAJAJ-AUTO", "TATAMOTORS",
    "ULTRACEMCO", "NESTLEIND", "POWERGRID", "NTPC", "ONGC",
    "SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "APOLLOHOSP",
    "ADANIENT", "ADANIPORTS", "TATACONSUM", "TATASTEEL", "JSWSTEEL",
    "HINDALCO", "COALINDIA", "BPCL", "IOC", "GRASIM",
    "SHREECEM", "ASIANPAINT", "BAJFINANCE", "BAJAJFINSV", "HCLTECH",
    "TECHM", "LT", "M&M", "EICHERMOT", "HEROMOTOCO",
    "TITAN", "BRITANNIA", "UPL", "INDUSINDBK",
]

EXCLUDED_SYMBOL = "SBILIFE"

# Numeric NSE_EQ instrument tokens (snapshot; mirrors backend/data/nifty50_symbols.py).
UPSTOX_NSE_EQ_TOKEN: dict[str, str] = {
    "RELIANCE": "2885",
    "TCS": "11536",
    "HDFCBANK": "1333",
    "INFY": "1594",
    "ICICIBANK": "4963",
    "HINDUNILVR": "1394",
    "ITC": "1660",
    "SBIN": "3045",
    "BHARTIARTL": "10604",
    "KOTAKBANK": "1922",
    "AXISBANK": "5900",
    "WIPRO": "3787",
    "MARUTI": "10999",
    "BAJAJ-AUTO": "16669",
    "TATAMOTORS": "3456",
    "ULTRACEMCO": "2775",
    "NESTLEIND": "17963",
    "POWERGRID": "14977",
    "NTPC": "11630",
    "ONGC": "2475",
    "SUNPHARMA": "3351",
    "DRREDDY": "881",
    "CIPLA": "694",
    "DIVISLAB": "10940",
    "APOLLOHOSP": "157",
    "ADANIENT": "25",
    "ADANIPORTS": "15083",
    "TATACONSUM": "3432",
    "TATASTEEL": "3499",
    "JSWSTEEL": "11723",
    "HINDALCO": "1363",
    "COALINDIA": "20374",
    "BPCL": "526",
    "IOC": "1624",
    "GRASIM": "1232",
    "SHREECEM": "3103",
    "ASIANPAINT": "236",
    "BAJFINANCE": "317",
    "BAJAJFINSV": "16675",
    "HCLTECH": "7229",
    "TECHM": "13538",
    "LT": "11483",
    "M&M": "2031",
    "EICHERMOT": "910",
    "HEROMOTOCO": "1348",
    "TITAN": "3506",
    "BRITANNIA": "547",
    "UPL": "2963",
    "INDUSINDBK": "5258",
}


def numeric_instrument_key(symbol: str) -> str | None:
    """Return 'NSE_EQ|{numeric_token}' for a symbol, or None if unknown."""
    token = UPSTOX_NSE_EQ_TOKEN.get(symbol.upper())
    return f"NSE_EQ|{token}" if token else None


def isin_instrument_key(symbol: str, isin: str) -> str:
    """Return 'NSE_EQ|{isin}' for a symbol."""
    return f"NSE_EQ|{isin.upper()}"
