"""Periodic status check — run anytime, no running process required.

Reports: run health, auth, rebalances/trades, and — the central comparison —
realized slippage vs the backtest's assumed cost per trade.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from paper_trading import config  # noqa: E402
from paper_trading.token_store import TokenStore  # noqa: E402


def _load_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _fmt_bps(v) -> str:
    if v is None:
        return "n/a"
    return f"{v:+.2f} bps"


def _pctile(vals, p):
    if not vals:
        return None
    vals = sorted(vals)
    idx = int(p / 100.0 * (len(vals) - 1))
    return vals[idx]


def main() -> int:
    state_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else config.STATE_DIR
    config.STATE_DIR = state_dir
    config.LOG_FILE = state_dir / "logs" / "events.jsonl"
    config.STATE_FILE = state_dir / "state.json"
    config.TOKENS_FILE = state_dir / "tokens.json"

    events = _load_events(config.LOG_FILE)
    state = {}
    if config.STATE_FILE.exists():
        try:
            state = json.loads(config.STATE_FILE.read_text())
        except Exception:  # noqa: BLE001
            pass

    print("=" * 72)
    print("  ALPHACORE PAPER TRADING — STATUS CHECK")
    print("=" * 72)

    if not events and not state:
        print("  No run data yet — scheduler has never booted (or state dir is "
              "wrong). Check states/paper_trading/.")
        return 1

    # ── run info ──
    boots = [e for e in events if e["type"] == "boot"]
    shutdowns = [e for e in events if e["type"] == "shutdown"]
    first = boots[0]["ts"] if boots else "?"
    print(f"\n  Run start:        {first}")
    print(f"  Boot count:       {len(boots)}   (clean shutdowns: {len(shutdowns)})")

    # ── auth ──
    ts = TokenStore(config.TOKENS_FILE)
    h = ts.health()
    auth = "OK" if h["sandbox_token_set"] and not h["sandbox_token_expired"] else "EXPIRED/MISSING"
    days = h["sandbox_days_left"]
    print(f"  Sandbox token:    {auth}"
          + (f"  ({days:.1f} days left)" if days is not None else ""))
    print(f"  Marketdata token: "
          f"{'OK' if h['marketdata_token_set'] and not h['marketdata_token_expired'] else 'EXPIRED/MISSING'}")

    # ── rebalances & trades ──
    reb_complete = [e for e in events if e["type"] == "rebalance_complete"]
    rebs = len(reb_complete)
    trades = [e for e in events if e["type"] == "trade"]
    rejects = [e for e in events if e["type"] == "order_terminal"
               and e["data"].get("status") in ("rejected", "rejected_at_placement", "cancelled")]
    sanity_fails = [e for e in events if e["type"] == "fill_sanity_fail"]
    pending = state.get("pending_orders", [])

    print(f"\n  Rebalances done:  {rebs}")
    if state.get("last_rebalance_date"):
        print(f"  Last rebalance:   {state['last_rebalance_date']}")
    print(f"  Trades recorded:  {len(trades)}")
    print(f"  Rejects/cancels:  {len(rejects)}   (see events.jsonl)")
    print(f"  Suspect fills:    {len(sanity_fails)}")
    print(f"  Unresolved orders:{len(pending)}")

    # equity
    marks = state.get("daily_marks", [])
    if marks:
        equity = marks[-1]["equity"]
        pnl = equity - config.INITIAL_CAPITAL
        ret = pnl / config.INITIAL_CAPITAL * 100
        print(f"  Equity:           Rs {equity:>12,.2f}  "
              f"(PnL {pnl:+,.2f}, {ret:+.2f}%)  [{len(marks)} daily marks]")
    else:
        print(f"  Equity:           {state.get('equity', config.INITIAL_CAPITAL):,.2f} (no marks yet)")

    # ── THE central comparison: realized slippage vs modeled ──
    print("\n  ── COST COMPARISON (per trade) ──")
    print("  backtest model per trade = impact(k=0.0015, ADV=qty) + half-spread")
    print("  + Rs 20 brokerage + 0.1% STT on sells (backend/engines/cost_model.py)")
    if not trades:
        print("  No trades yet — nothing to compare.")
    else:
        fills = [t["data"] for t in trades]
        sandbox_fills = [f for f in fills if f.get("fill_source") == "sandbox"]
        fallback_fills = [f for f in fills if f.get("fill_source") != "sandbox"]

        s_vals = [f["slippage_bps"] for f in fills if f.get("slippage_bps") is not None]
        m_vals = [f["modeled_cost_rs"] for f in fills if f.get("modeled_cost_rs") is not None]
        s_rs = [f["slippage_rs"] for f in fills if f.get("slippage_rs") is not None]
        spread_live = [f["spread_bps_live"] for f in fills if f.get("spread_bps_live")]

        print(f"  Trades: {len(fills)}  "
              f"(sandbox fills: {len(sandbox_fills)}, live-quote fallback: {len(fallback_fills)})")
        print(f"  Realized slippage   mean {_fmt_bps(_mean(s_vals))}  "
              f"median {_fmt_bps(median(s_vals) if s_vals else None)}  "
              f"p10 {_fmt_bps(_pctile(s_vals, 10))}  p90 {_fmt_bps(_pctile(s_vals, 90))}")
        print(f"  Realized slippage   Rs/trade mean {_mean(s_rs):.2f}" if s_rs else "")
        print(f"  Modeled cost        Rs/trade mean {_mean(m_vals):.2f}" if m_vals else "")
        print(f"  Live spread at fills: mean {_mean(spread_live):.1f} bps" if spread_live else "")

        n_pos = sum(1 for v in s_vals if v is not None and v >= 0)
        if s_vals:
            print(f"  Adverse-fill count: {n_pos}/{len(s_vals)} "
                  f"(>0 = buying above / selling below live mid)")

    # kill switch
    if config.KILL_FILE.exists():
        print(f"\n  KILL SWITCH: FILE PRESENT — scheduler will stop (or is stopped).")
    print("\n  Log: " + str(config.LOG_FILE))
    return 0


def _mean(vals):
    if not vals:
        return None
    return sum(vals) / len(vals)


if __name__ == "__main__":
    sys.exit(main())
