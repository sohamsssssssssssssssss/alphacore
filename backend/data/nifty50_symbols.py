from __future__ import annotations

# Nifty 50 symbols with their Angel One token IDs
# Source: Angel One instrument list (NSE segment)
# Last updated: May 2026
# To update tokens: download master contract from Angel One API
#   GET https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json

NIFTY50_SYMBOLS: list[str] = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
    "AXISBANK", "WIPRO", "MARUTI", "BAJAJ-AUTO", "TATAMOTORS",
    "ULTRACEMCO", "NESTLEIND", "POWERGRID", "NTPC", "ONGC",
    "SUNPHARMA", "DRREDDY", "CIPLA", "DIVISLAB", "APOLLOHOSP",
    "ADANIENT", "ADANIPORTS", "TATACONSUM", "TATASTEEL", "JSWSTEEL",
    "HINDALCO", "COALINDIA", "BPCL", "IOC", "GRASIM",
    "SHREECEM", "ASIANPAINT", "BAJFINANCE", "BAJAJFINSV", "HCLTECH",
    "TECHM", "LT", "M&M", "EICHERMOT", "HEROMOTOCO",
    "TITAN", "BRITANNIA", "UPL", "INDUSINDBK", "SBILIFE",
]

# Angel One NSE token map for Nifty 50
# Tokens sourced from Angel One OpenAPI master contract
NIFTY50_TOKEN_MAP: dict[str, str] = {
    "RELIANCE":   "2885",
    "TCS":        "11536",
    "HDFCBANK":   "1333",
    "INFY":       "1594",
    "ICICIBANK":  "4963",
    "HINDUNILVR": "1394",
    "ITC":        "1660",
    "SBIN":       "3045",
    "BHARTIARTL": "10604",
    "KOTAKBANK":  "1922",
    "AXISBANK":   "5900",
    "WIPRO":      "3787",
    "MARUTI":     "10999",
    "BAJAJ-AUTO": "16669",
    "TATAMOTORS": "3456",
    "ULTRACEMCO": "2775",
    "NESTLEIND":  "17963",
    "POWERGRID":  "14977",
    "NTPC":       "11630",
    "ONGC":       "2475",
    "SUNPHARMA":  "3351",
    "DRREDDY":    "881",
    "CIPLA":      "694",
    "DIVISLAB":   "10940",
    "APOLLOHOSP": "157",
    "ADANIENT":   "25",
    "ADANIPORTS": "15083",
    "TATACONSUM": "3432",
    "TATASTEEL":  "3499",
    "JSWSTEEL":   "11723",
    "HINDALCO":   "1363",
    "COALINDIA":  "20374",
    "BPCL":       "526",
    "IOC":        "1624",
    "GRASIM":     "1232",
    "SHREECEM":   "3103",
    "ASIANPAINT": "236",
    "BAJFINANCE": "317",
    "BAJAJFINSV": "16675",
    "HCLTECH":    "7229",
    "TECHM":      "13538",
    "LT":         "11483",
    "M&M":        "2031",
    "EICHERMOT":  "910",
    "HEROMOTOCO": "1348",
    "TITAN":      "3506",
    "BRITANNIA":  "547",
    "UPL":        "2963",
    "INDUSINDBK": "5258",
    "SBILIFE":    "21808",
}


def get_nifty50_tokens() -> list[str]:
    """Return list of Angel One token IDs for all Nifty 50 symbols."""
    return list(NIFTY50_TOKEN_MAP.values())


def get_token_for_symbol(symbol: str) -> str | None:
    """Return Angel One token ID for a given symbol."""
    return NIFTY50_TOKEN_MAP.get(symbol.upper())


def get_symbol_for_token(token: str) -> str | None:
    """Return symbol name for a given Angel One token ID."""
    return next((s for s, t in NIFTY50_TOKEN_MAP.items() if t == token), None)
