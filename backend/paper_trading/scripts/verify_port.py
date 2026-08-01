"""Verify the ported signal reproduces the backtest math on repo data.

Loads the 49-symbol CSVs (same data as the backtest), seeds the close history,
and confirms the trailing-20-day-return ranking picks argmax (long) / argmin
(short) at the 3 most recent dates. Prints PASS/FAIL per check.

Run: python3.11 backend/paper_trading/scripts/verify_port.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from paper_trading import config  # noqa: E402
from paper_trading.market_data import CloseHistory  # noqa: E402
from paper_trading.strategy import verify_port  # noqa: E402


def main() -> int:
    state_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else config.STATE_DIR
    config.STATE_DIR = state_dir
    config.CLOSE_HISTORY_FILE = state_dir / "close_history.json"

    symbols = sorted(p.stem for p in config.DATA_DIR_50.glob("*.csv"))
    print(f"Universe: {len(symbols)} symbols")

    hist = CloseHistory()
    if not hist.load():
        n = hist.seed_from_csv(symbols)
        print(f"Seeded {n} symbols from repo CSVs (seed date {hist.seed_date})")
    else:
        print(f"Loaded existing close history (latest {hist.latest_date()})")

    result = verify_port(hist, symbols)
    ok = result["ok"]
    for check in result["checks"]:
        mark = "PASS" if check["ok"] else "FAIL"
        print(f"[{mark}] long={check['long']} short={check['short']} "
              f"n_ranked={check['n_ranked']} "
              f"long_ret={check['long_ret']:+.4%} short_ret={check['short_ret']:+.4%}")
    print()
    if ok:
        print("RESULT: ported signal matches backtest math (argmax/argmin of "
              "pct_change(20)).")
        return 0
    print("RESULT: MISMATCH — do not run the scheduler until this is fixed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
