"""Step 1.4 — harmless sandbox connectivity verification.

Places NO orders. Checks, in order:
  1. sandbox base URL resolves (PAPER_SANDBOX_URL guard)
  2. sandbox token present (env or tokens.json)
  3. sandbox order book readable (should be empty on a fresh sandbox)
  4. read-only market-data token present and live quotes fetchable
  5. instrument resolution for the 49-symbol universe (API vs fallback)

Exit code 0 = all checks pass; nonzero otherwise. Safe to re-run anytime.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from paper_trading import config  # noqa: E402
from paper_trading.instruments import InstrumentCache, FALLBACK_INSTRUMENT_KEYS  # noqa: E402
from paper_trading.token_store import TokenStore  # noqa: E402
from paper_trading.upstox_client import MarketDataClient, OrderClient  # noqa: E402

PASS, FAIL = "PASS", "FAIL"


def main() -> int:
    failures = 0
    state_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else config.STATE_DIR
    config.STATE_DIR = state_dir
    config.TOKENS_FILE = state_dir / "tokens.json"

    symbols = sorted(p.stem for p in config.DATA_DIR_50.glob("*.csv"))
    print(f"Universe: {len(symbols)} symbols from {config.DATA_DIR_50.name}")

    # 1 — sandbox URL guard
    try:
        url = config.sandbox_url()
        print(f"[{PASS}] sandbox base URL = {url}")
    except RuntimeError as exc:
        print(f"[{FAIL}] {exc}")
        failures += 1
        return 1

    # 2 — sandbox token
    ts = TokenStore(config.TOKENS_FILE)
    health = ts.health()
    if health["sandbox_token_set"] and not health["sandbox_token_expired"]:
        days = health["sandbox_days_left"]
        dl = f"{days:.1f} days left" if days is not None else "expiry unknown"
        print(f"[{PASS}] sandbox token set ({dl}); source={health['sources']['sandbox']}")
    else:
        print(f"[{FAIL}] sandbox token missing or expired — create sandbox app + "
              f"generate token at account.upstox.com/developer/apps#sandbox, then "
              f"set PAPER_SANDBOX_TOKEN (+ expiry) in backend/paper_trading/.env "
              f"or write states/paper_trading/tokens.json")
        failures += 1
        return 1

    # 3 — sandbox order book (harmless read; no orders placed)
    oc = OrderClient()
    try:
        book = oc.get_order_book(ts.tokens.sandbox_token)
        orders = (book.get("data") or [])
        print(f"[{PASS}] sandbox order book readable — {len(orders)} orders "
              f"(expected 0 on fresh sandbox)")
    except Exception as exc:  # noqa: BLE001
        print(f"[{FAIL}] sandbox order book failed: {exc!r}")
        print("        NOTE: if this fails, order-details/order-book endpoints "
              "may not be sandbox-enabled; orders are still placeable. See "
              "PAPER_TRADING_LOG.md.")
        failures += 1

    # 4 — market data (read-only, live host)
    md = MarketDataClient()
    if health["marketdata_token_set"] and not health["marketdata_token_expired"]:
        try:
            body = md.market_status(ts.tokens.marketdata_token)
            nse = ((body.get("data") or {}).get("exchange") or {}).get("NSE") or {}
            print(f"[{PASS}] live market status readable — NSE status: "
                  f"{nse.get('status', 'unknown')}")
        except Exception as exc:  # noqa: BLE001
            print(f"[{FAIL}] market status call failed: {exc!r}")
            failures += 1
    else:
        print(f"[FAIL] market-data token missing — needed for live quotes "
              f"(read-only). See README section 'Market data token'.")
        failures += 1

    # 5 — instrument resolution
    if health["marketdata_token_set"]:
        cache = InstrumentCache()
        n, source = cache.fetch(md, ts.tokens.marketdata_token, symbols)
        if n >= len(symbols):
            print(f"[{PASS}] instruments resolved via API: {n}/{len(symbols)} "
                  f"symbols")
        else:
            print(f"[FAIL] instruments API resolved only {n}/{len(symbols)} — "
                  f"fallback map covers {len(FALLBACK_INSTRUMENT_KEYS)}. "
                  f"Inspect network/keys.")
            failures += 1
    else:
        print(f"[WARN] instruments not verified (no market-data token) — "
              f"fallback static map has {len(FALLBACK_INSTRUMENT_KEYS)} keys")

    print()
    if failures:
        print(f"RESULT: {failures} check(s) failed — see above.")
        return 1
    print("RESULT: all checks passed. Safe to start the scheduler "
          "(python3.11 backend/paper_trading/scheduler.py).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
